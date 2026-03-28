"""
Layer 3 — Tools : Gemini Skills (SnackFlow v3.0)
=================================================
Deux Skills rigoureuses appuyées sur les Structured Outputs de Gemini 2.0 Flash.
Zéro parsing regex, zéro chat libre, zéro JSON manuel.

Architecture BLAST — Skills :
  ┌──────────────────────────────────────────────────┐
  │  SKILL 1 — parse_order_skill(user_text)          │
  │  Texte libre → HubRiseOrder (Pydantic-validated) │
  ├──────────────────────────────────────────────────┤
  │  SKILL 2 — generate_upsell_skill(order_data)     │
  │  Panier JSON → UpsellSuggestion (AOV pur)        │
  └──────────────────────────────────────────────────┘

Principe fondamental :
  - Structured Output : response_mime_type="application/json" + response_schema
  - Gemini garantit le format JSON → Pydantic valide la structure
  - Fallback déterministe si Gemini indisponible (non bloquant)
  - Zéro politesse dans les prompts → économie maximale de tokens

Variables .env requises :
  GEMINI_API_KEY   Clé API Google AI Studio (https://aistudio.google.com)
  GEMINI_MODEL     Modèle (défaut : gemini-2.0-flash)

Schémas HubRise v1 (source : developers.hubrise.com) :
  - quantity   → toujours string ("2", "1.5")
  - price      → "8.50 EUR" (Money string)
  - options    → [{name: str, price: str}] (modifiers/toppings)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()

# ─── Logger ────────────────────────────────────────────────────────────────────

logger = logging.getLogger("snack_flow.gemini")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s | gemini_skill | %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ─── Config ────────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


# =============================================================================
# SCHÉMAS PYDANTIC — Source de vérité structurelle
# =============================================================================

class OrderOption(BaseModel):
    """Modifier/topping appliqué à un article (ex: sans oignon, extra sauce)."""
    model_config = {"coerce_numbers_to_str": True}

    name: str = Field(..., description="Nom de l'option ou du modificateur")
    price: str = Field(default="0.00 EUR", description="Prix de l'option au format HubRise Money")

    @field_validator("price")
    @classmethod
    def ensure_money_format(cls, v: str) -> str:
        """Garantit le format 'X.XX EUR' même si Gemini retourne un float."""
        v = str(v).strip()
        if v and not v.endswith("EUR"):
            try:
                return f"{float(v):.2f} EUR"
            except ValueError:
                pass
        return v


class OrderItem(BaseModel):
    """
    Article commandé au format HubRise v1.

    Note HubRise : quantity et price sont TOUJOURS des strings.
    """
    model_config = {"coerce_numbers_to_str": True}

    product_name: str = Field(..., description="Nom du produit tel qu'énoncé par le client")
    quantity: str     = Field(default="1", description="Quantité commandée (string HubRise)")
    price: str        = Field(default="0.00 EUR", description="Prix unitaire HubRise Money")
    options: List[OrderOption] = Field(default_factory=list, description="Modificateurs/toppings")
    customer_notes: Optional[str] = Field(default=None, description="Note spécifique à cet article")

    @field_validator("quantity")
    @classmethod
    def ensure_string_quantity(cls, v) -> str:
        """HubRise exige quantity comme string (ex: '2', '1.5')."""
        return str(v).strip() or "1"

    @field_validator("price")
    @classmethod
    def ensure_money_format(cls, v: str) -> str:
        v = str(v).strip()
        if v and not v.endswith("EUR"):
            try:
                return f"{float(v):.2f} EUR"
            except ValueError:
                pass
        return v

    def to_legacy_dict(self) -> dict:
        """
        Convertit vers le format legacy {name, qty, price} pour la compatibilité
        Supabase + hubrise_tool._map_items().
        """
        try:
            qty = int(float(self.quantity))
        except (ValueError, TypeError):
            qty = 1
        try:
            price_val = float(self.price.replace(" EUR", "").strip())
        except (ValueError, AttributeError):
            price_val = 0.0

        return {
            "name":    self.product_name,
            "qty":     qty,
            "price":   price_val if price_val > 0 else None,
            "options": [o.name for o in self.options],
        }


class HubRiseOrder(BaseModel):
    """
    Commande complète au format HubRise v1.
    Produit de la Skill 1 (OrderParser).
    """
    items: List[OrderItem] = Field(default_factory=list, description="Liste des articles commandés")
    customer_notes: Optional[str] = Field(
        default=None,
        description="Note globale du client pour toute la commande"
    )
    service_type: str = Field(
        default="collection",
        description="Type de service HubRise — toujours 'collection' pour SnackFlow"
    )

    def to_legacy_items(self) -> list:
        """Retourne la liste d'items au format legacy pour Supabase/HubRise push."""
        return [item.to_legacy_dict() for item in self.items]

    def is_empty(self) -> bool:
        return len(self.items) == 0


class UpsellSuggestion(BaseModel):
    """
    Suggestion d'upsell produite par la Skill 2 (LogicalUpseller).

    RÈGLE MÉTIER ABSOLUE :
      - Aucune réduction, aucun code promo, aucun produit gratuit.
      - Objectif unique : augmentation pure du panier moyen (AOV).
    """
    suggested_item: str   = Field(..., description="Nom du produit suggéré")
    reason: str           = Field(..., description="Justification interne (ne pas envoyer au client)")
    whatsapp_message: str = Field(
        ...,
        description=(
            "Message WhatsApp à envoyer au client. "
            "Naturel, concis (1-2 phrases max). "
            "INTERDIT : réduction, promo, produit gratuit."
        )
    )


# =============================================================================
# CLIENT GEMINI — Lazy init thread-safe
# =============================================================================

_gemini_lock   = threading.Lock()
_genai_module  = None


def _get_genai():
    """Retourne le module google.generativeai (lazy import, thread-safe)."""
    global _genai_module
    with _gemini_lock:
        if _genai_module is not None:
            return _genai_module

        if not GEMINI_API_KEY:
            raise RuntimeError(
                "❌ GEMINI_API_KEY manquante dans .env\n"
                "   Créez une clé sur https://aistudio.google.com"
            )
        try:
            import google.generativeai as genai
            genai.configure(api_key=GEMINI_API_KEY)
            _genai_module = genai
            logger.info("✅ Gemini configuré → modèle=%s", GEMINI_MODEL)
            return _genai_module
        except ImportError:
            raise RuntimeError(
                "❌ Package 'google-generativeai' non installé.\n"
                "   Exécutez : pip install google-generativeai"
            )


# =============================================================================
# SKILL 1 — ORDER PARSER (Text → HubRiseOrder)
# =============================================================================

_ORDER_PARSER_SYSTEM = (
    "Tu es un extracteur de données POS. "
    "Ta seule mission est de transformer le texte client en JSON HubRise. "
    "Ne discute jamais. "
    "Règles absolues : "
    "1. Extrais uniquement les articles commandés. "
    "2. Si un produit n'est pas clair, extrais-le tel quel avec price='0.00 EUR'. "
    "3. Consolide les doublons (ex: '2 burgers' + 'un burger' → quantity='3'). "
    "4. Normalise les noms en français standard et capitalise la première lettre. "
    "5. Ne jamais inventer un prix. "
    "6. Les options/modificateurs vont dans le champ options de l'article concerné. "
    "7. Si aucun article n'est trouvé, retourne items=[]."
)

_ORDER_PARSER_GENERATION_CONFIG = {
    "response_mime_type": "application/json",
    "temperature": 0.0,  # Déterministe — zéro créativité
    "top_p": 1.0,
    "max_output_tokens": 512,
}


def parse_order_skill(user_text: str, menu_context: dict = None) -> HubRiseOrder:
    """
    SKILL 1 — Order Parser.

    Transforme un message texte libre client en commande structurée HubRise.
    Utilise les Structured Outputs de Gemini : zéro regex, zéro json.loads manuel.

    :param user_text: Texte brut du message WhatsApp client.
    :param menu_context: Dictionnaire optionnel représentant le catalogue produit du snack.
    :return: HubRiseOrder validé par Pydantic.
             Fallback : HubRiseOrder avec un item encapsulé si Gemini indisponible.

    Exemples :
      "2 burgers avec sauce béarnaise et 1 frite"
      → HubRiseOrder(items=[
            OrderItem(product_name="Burger", quantity="2", options=[OrderOption(name="sauce béarnaise")]),
            OrderItem(product_name="Frites", quantity="1"),
        ])
    """
    if not user_text or not user_text.strip():
        logger.info("⚠️  parse_order_skill → texte vide → HubRiseOrder vide retourné")
        return HubRiseOrder(items=[])

    text = user_text.strip()

    try:
        genai = _get_genai()

        # Construction dynamique du System Prompt
        sys_prompt = _ORDER_PARSER_SYSTEM
        if menu_context:
            menu_str = json.dumps(menu_context, ensure_ascii=False)
            sys_prompt += (
                f"\n\nVoici le catalogue officiel du snack : {menu_str}. "
                "Ta mission est de mapper les envies du client EXCLUSIVEMENT sur les produits de ce catalogue. "
                "Si un produit demandé n'existe pas dans le catalogue, l'extraction doit quand même se faire, "
                "mais tu dois l'indiquer explicitement dans le champ customer_notes. "
                "IMPORTANT : si le catalogue contient une clé '_out_of_stock', les produits listés "
                "sont en rupture de stock — tu NE DOIS PAS les inclure dans la commande. "
                "Informe le client dans customer_notes si son article est indisponible."
            )

        # Structured Output : Gemini retourne directement un JSON conforme au schéma
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=sys_prompt,
        )

        response = model.generate_content(
            text,
            generation_config={
                **_ORDER_PARSER_GENERATION_CONFIG,
                "response_schema": HubRiseOrder,
            },
        )

        raw_json = response.text.strip()
        order_data = json.loads(raw_json)
        order = HubRiseOrder.model_validate(order_data)

        logger.info(
            "✅ parse_order_skill → %d article(s) | '%s...'",
            len(order.items), text[:40],
        )
        return order

    except RuntimeError as e:
        logger.warning("⚠️  Gemini indisponible (%s) → fallback texte brut", e)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("⚠️  parse_order_skill erreur (%s) → fallback texte brut", type(e).__name__)

    return _fallback_order(text)


def _fallback_order(text: str) -> HubRiseOrder:
    """
    Fallback déterministe (sans LLM).
    Encapsule le texte brut comme un article unique avec price=0.
    Garantit que le webhook ne crash jamais.
    """
    logger.info("🔄 Fallback order → encapsulation texte brut")
    return HubRiseOrder(
        items=[
            OrderItem(
                product_name=text[:200].strip(),
                quantity="1",
                price="0.00 EUR",
                customer_notes="[Extraction automatique échouée — vérification manuelle requise]",
            )
        ],
        customer_notes="[Commande brute — parsing indisponible]",
    )


# =============================================================================
# SKILL 2 — LOGICAL UPSELLER (HubRiseOrder → UpsellSuggestion)
# =============================================================================

_UPSELL_SYSTEM = (
    "Tu es un conseiller commercial de snack-bar. "
    "Analyse le JSON du panier client et propose UNE SEULE suggestion d'article complémentaire. "
    "Logique métier STRICTE : "
    "  - Si aucune boisson n'est présente dans le panier → suggère une boisson. "
    "  - Si le menu semble incomplet (pas d'accompagnement/frites) → suggère un accompagnement. "
    "  - Si le panier semble complet → suggère un dessert. "
    "INTERDICTION FORMELLE ET ABSOLUE : "
    "  - Ne jamais proposer de réduction. "
    "  - Ne jamais proposer de code promo. "
    "  - Ne jamais proposer un produit gratuit. "
    "  - Ne jamais mentionner un prix inférieur au prix normal. "
    "  - L'objectif est l'augmentation pure du panier moyen (AOV). "
    "Le champ 'reason' est INTERNE (pourquoi tu suggères), il n'est jamais envoyé au client. "
    "Le champ 'whatsapp_message' est le texte exact à envoyer via WhatsApp : "
    "  naturel, chaleureux, concis (1-2 phrases maximum). "
    "  Commence TOUJOURS par un emoji approprié."
)

_UPSELL_GENERATION_CONFIG = {
    "response_mime_type": "application/json",
    "temperature": 0.3,  # Légère créativité pour la formulation, mais cadré
    "top_p": 0.9,
    "max_output_tokens": 256,
}


def generate_upsell_skill(order_data: HubRiseOrder, menu_context: dict = None) -> Optional[UpsellSuggestion]:
    """
    SKILL 2 — Logical Upseller.

    Analyse le panier JSON et génère une suggestion d'upsell ciblée.
    Contrainte absolue : zéro réduction, zéro promo, zéro produit gratuit.
    Objectif : augmentation pure du panier moyen (AOV).

    :param order_data: HubRiseOrder produit par parse_order_skill.
    :param menu_context: Dictionnaire optionnel représentant le catalogue produit du snack.
    :return: UpsellSuggestion ou None si panier vide / Gemini indisponible.
    """
    if not order_data or order_data.is_empty():
        logger.info("⚠️  generate_upsell_skill → panier vide → pas de suggestion")
        return None

    # Sérialise le panier pour le contexte du prompt
    basket_json = json.dumps(
        order_data.model_dump(exclude={"service_type"}),
        ensure_ascii=False,
        indent=2,
    )
    prompt = f"Panier client :\n{basket_json}"

    try:
        genai = _get_genai()

        # Construction dynamique du System Prompt
        sys_prompt = _UPSELL_SYSTEM
        if menu_context:
            menu_str = json.dumps(menu_context, ensure_ascii=False)
            sys_prompt += (
                f"\n\nVoici le catalogue officiel du snack : {menu_str}. "
                "L'article que tu suggères DOIT ÊTRE présent dans ce catalogue. "
                "Ne suggère jamais un produit générique s'il n'est pas explicitement listé. "
                "IMPORTANT : si le catalogue contient une clé '_out_of_stock', "
                "ne suggère JAMAIS un produit figurant dans cette liste — il est en rupture de stock."
            )

        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=sys_prompt,
        )

        response = model.generate_content(
            prompt,
            generation_config={
                **_UPSELL_GENERATION_CONFIG,
                "response_schema": UpsellSuggestion,
            },
        )

        raw_json = response.text.strip()
        suggestion_data = json.loads(raw_json)
        suggestion = UpsellSuggestion.model_validate(suggestion_data)

        logger.info(
            "✅ generate_upsell_skill → suggestion : '%s' | raison : '%s'",
            suggestion.suggested_item, suggestion.reason,
        )
        return suggestion

    except RuntimeError as e:
        logger.warning("⚠️  Gemini indisponible pour upsell (%s) → pas de suggestion", e)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("⚠️  generate_upsell_skill erreur (%s) → pas de suggestion", type(e).__name__)

    return None


# =============================================================================
# TEST RAPIDE (python -m layer3_tools.gemini_tool)
# =============================================================================

if __name__ == "__main__":
    import sys

    test_messages = [
        "2 burgers avec sauce béarnaise et 1 grande frite",
        "3 pizzas margherita et 2 coca",
        "Je voudrais un sandwich jambon fromage",
        "Bonsoir ! Un menu complet avec frites, burger et une limonade",
        "kebab x2 sans oignon",
        "Bonjour",  # → items vides attendus
    ]

    print("🧪 SKILL 1 — OrderParser\n" + "─" * 60)
    for msg in test_messages:
        print(f"\n  📩 Input  : {msg!r}")
        order = parse_order_skill(msg)
        print(f"  📦 Items  : {order.model_dump_json(indent=2)}")

        print("\n  🎯 SKILL 2 — UpsellSuggestion :")
        suggestion = generate_upsell_skill(order)
        if suggestion:
            print(f"  ➕ Produit suggéré : {suggestion.suggested_item}")
            print(f"  📱 Message WA      : {suggestion.whatsapp_message}")
            print(f"  🔍 Raison interne  : {suggestion.reason}")
        else:
            print("  ➖ Aucune suggestion (panier vide ou Gemini indisponible)")
        print("─" * 60)

    sys.exit(0)
