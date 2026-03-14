"""
Layer 3 — Tools : Gemini LLM Order Parser (Snack-Flow v3.0)
============================================================
Transforme un texte libre client ("2 burgers et 1 frite")
en une liste structurée JSON utilisable dans la table `orders.items`.

Architecture :
  - Modèle : gemini-2.0-flash (Google Generative AI)
  - Parsing JSON strict via prompt engineering
  - Fallback deterministe si LLM indisponible (encapsulation texte brut)
  - Zéro prix inventé : price=null si non mentionné

Variables .env requises :
  GEMINI_API_KEY   Clé API Google AI Studio (https://aistudio.google.com)

Output schema :
  [
    {"name": "Burger classique", "qty": 2, "price": null},
    {"name": "Frites",           "qty": 1, "price": null}
  ]
"""

import json
import logging
import os
import re
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ─── Logger ────────────────────────────────────────────────────────────────────

logger = logging.getLogger("snack_flow.gemini")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s | gemini_tool | %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ─── Config ────────────────────────────────────────────────────────────────────

GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL     = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Prompt système strict — retourne UNIQUEMENT du JSON
_SYSTEM_PROMPT = """
Tu es un assistant de commande pour un snack-bar.
Ton unique rôle : extraire les articles commandés depuis un message client en texte libre.

Règles absolues :
1. Réponds UNIQUEMENT avec un tableau JSON valide, rien d'autre.
2. Chaque élément a les clés : "name" (str), "qty" (int ≥ 1), "price" (null).
3. Si tu ne trouves aucun article, retourne [].
4. Ne jamais inventer des prix — toujours null.
5. Consolide les doublons (ex: "2 burgers" + "un burger" → qty: 3).
6. Normalise les noms en français standard.

Exemple :
  Input  : "Je voudrais 2 burgers, 1 frite et une boisson s'il vous plaît"
  Output : [{"name": "Burger", "qty": 2, "price": null}, {"name": "Frites", "qty": 1, "price": null}, {"name": "Boisson", "qty": 1, "price": null}]
""".strip()


# ─── Initialisation du client Gemini ──────────────────────────────────────────

import threading as _threading
_gemini_client = None
_gemini_lock   = _threading.Lock()


def _get_gemini_client():
    """Retourne le client Google Generative AI (lazy init, thread-safe)."""
    global _gemini_client
    with _gemini_lock:
        # Double-checked locking: re-test inside the lock
        if _gemini_client is not None:
            return _gemini_client

        if not GEMINI_API_KEY:
            raise RuntimeError(
                "❌ GEMINI_API_KEY manquante dans .env\n"
                "   Créez une clé sur https://aistudio.google.com"
            )

        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            _gemini_client = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=_SYSTEM_PROMPT,
            )
            logger.info("✅ Gemini client initialisé → modèle=%s", GEMINI_MODEL)
            return _gemini_client
        except ImportError:
            raise RuntimeError(
                "❌ Package 'google-generativeai' non installé.\n"
                "   Exécutez : pip install google-generativeai"
            )


# =============================================================================
# FONCTION PRINCIPALE : parse_order_text
# =============================================================================

def parse_order_text(message_text: str) -> list:
    """
    Parse un texte libre client et retourne une liste d'articles structurés.

    Utilise Gemini pour extraire articles + quantités.
    Fallback deterministe si LLM indisponible (encapsule le texte brut).

    :param message_text: Texte brut du message WhatsApp client.
    :return: Liste JSONB ex: [{"name": "Burger", "qty": 2, "price": null}]

    Exemples :
      "2 burgers et 1 frite"
      → [{"name": "Burger", "qty": 2, "price": null},
         {"name": "Frites",  "qty": 1, "price": null}]

      "Bonjour !"
      → []
    """
    if not message_text or not message_text.strip():
        return []

    # ── Tentative LLM Gemini ──────────────────────────────────────────────────
    try:
        client = _get_gemini_client()
        response = client.generate_content(message_text.strip())
        raw = response.text.strip()

        # Nettoyage des fences markdown éventuels (```json ... ```)
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

        items = json.loads(raw)

        if not isinstance(items, list):
            raise ValueError(f"Réponse Gemini non-liste : {type(items)}")

        # Validation minimale de chaque item
        validated = []
        for item in items:
            if isinstance(item, dict) and "name" in item:
                validated.append({
                    "name":  str(item.get("name", "")).strip(),
                    "qty":   max(1, int(item.get("qty", 1))),
                    "price": item.get("price"),  # null par défaut
                })

        logger.info(
            "✅ parse_order_text → %d article(s) extraits | '%s...'",
            len(validated), message_text[:40]
        )
        return validated

    except RuntimeError as e:
        # GEMINI_API_KEY absente ou package manquant → fallback
        logger.warning("⚠️  Gemini indisponible (%s) → fallback texte brut", e)
    except json.JSONDecodeError as e:
        logger.warning("⚠️  Gemini JSON invalide (%s) → fallback texte brut", e)
    except Exception as e:
        logger.warning("⚠️  Gemini erreur inattendue (%s) → fallback texte brut", e)

    # ── Fallback : encapsulation texte brut ───────────────────────────────────
    return _fallback_parse(message_text)


def _fallback_parse(text: str) -> list:
    """
    Fallback deterministe (sans LLM).
    Encapsule le texte brut comme un article unique.
    Tente une extraction naive pour les patterns "N article".

    :param text: Texte brut du message.
    :return: Liste d'items [{...}]
    """
    items = []

    # Pattern simple : "2 burgers", "un sandwich", "3 pizzas"
    pattern = re.compile(
        r"\b(\d+|un|une|deux|trois|quatre|cinq)\s+([a-zA-Zàâäéèêëïîôùûüÿç\s-]{2,30})",
        re.IGNORECASE
    )
    _num_words = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5}

    for match in pattern.finditer(text):
        qty_str = match.group(1).lower()
        name    = match.group(2).strip().rstrip("s")  # dé-pluralise naïvement

        qty = _num_words.get(qty_str, None) or int(qty_str)
        items.append({"name": name.capitalize(), "qty": qty, "price": None})

    if items:
        logger.info("✅ Fallback parse → %d article(s) extrait(s) (regex)", len(items))
        return items

    # Dernier recours : texte brut complet comme article unique
    logger.info("✅ Fallback parse → texte brut encapsulé")
    return [{"name": text[:200].strip(), "qty": 1, "price": None}]


# =============================================================================
# TEST RAPIDE (python -m layer3_tools.gemini_tool)
# =============================================================================

if __name__ == "__main__":
    test_messages = [
        "Je voudrais 2 burgers et 1 frite s'il vous plaît !",
        "3 pizzas margherita et 2 coca",
        "Bonjour, c'est possible d'avoir un sandwich jambon fromage ?",
        "Bonsoir !",
    ]

    print("🧪 Test de parse_order_text()\n" + "─" * 50)
    for msg in test_messages:
        result = parse_order_text(msg)
        print(f"  Input  : {msg!r}")
        print(f"  Output : {json.dumps(result, ensure_ascii=False)}\n")
