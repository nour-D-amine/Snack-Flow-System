"""
whatsapp_tool.py — Snack-Flow WhatsApp Layer (v2.0 Full-WhatsApp)
=================================================================
Intègre l'API Cloud officielle de Meta pour l'envoi de messages
interactifs à boutons (CTA URL + text) et tickets cuisine.

Architecture v2.0 — System User Token :
  - Un SEUL token d'accès (System User Token du Business Manager Meta).
  - Chargé depuis les variables d'environnement (WHATSAPP_ACCESS_TOKEN).
  - Le `phone_number_id` est passé explicitement à chaque appel.
  - Résultat : zéro dépendance à GSheets, zéro token par tenant.

Principes :
  - Zéro clé en dur : WHATSAPP_ACCESS_TOKEN et WHATSAPP_PHONE_NUMBER_ID
    sont chargés depuis .env (fallback config dict pour compat legacy).
  - Self-Healing  : les erreurs API sont loguées sans faire planter le flux.
  - Multi-Tenant  : le phone_number_id du tenant est extrait du dict config.
  - Vitesse       : appels HTTP synchrones légers (< 1 s hors latence réseau).

Fonctions publiques :
  - send_interactive_menu(config, customer_phone)   → dict
  - send_loyalty_welcome(config, customer_phone)    → dict
  - send_kitchen_ticket(config, order_data)         → dict
  - send_text_message(config, customer_phone, body) → dict  [utilitaire interne]
"""

import json
import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Logger dédié ─────────────────────────────────────────────────────────────

logger = logging.getLogger("snack_flow.whatsapp")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s | whatsapp_tool | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ─── Constantes versionnées ───────────────────────────────────────────────────

META_API_VERSION = "v19.0"
META_GRAPH_BASE  = "https://graph.facebook.com"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNES
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_credentials(config: dict) -> tuple[str, str]:
    """
    Résout le phone_number_id et le System User Token pour un appel API.

    Priorité :
      1. config["whatsapp_phone_id"] ou config["whatsapp_phone_number_id"] (issu de Supabase)
      2. Variable d'env WHATSAPP_PHONE_NUMBER_ID (fallback / single-tenant)

    Le token suit TOUJOURS la même hiérarchie :
      1. Variable d'env WHATSAPP_ACCESS_TOKEN (System User Token — recommandé)
      2. config["whatsapp_token"] (legacy compat)

    :param config: Dict de config issu de supabase_tool.get_snack_config().
    :return: (phone_number_id, access_token)
    :raises ValueError: Si l'un des deux est absent.
    """
    # ── phone_number_id ──────────────────────────────────────────────────────
    phone_id = (
        str(config.get("whatsapp_phone_id", "")).strip()
        or str(config.get("whatsapp_phone_number_id", "")).strip()
        or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    )
    if not phone_id:
        raise ValueError(
            f"[{config.get('snack_id') or config.get('id', '?')}] "
            "'whatsapp_phone_number_id' introuvable dans config ni dans WHATSAPP_PHONE_NUMBER_ID."
        )

    # ── access_token (System User Token) ─────────────────────────────────────
    token = (
        os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
        or str(config.get("whatsapp_token", "")).strip()
    )
    if not token:
        raise ValueError(
            "WHATSAPP_ACCESS_TOKEN absent des variables d'environnement. "
            "Configurez un System User Token dans le Business Manager Meta."
        )

    return phone_id, token


def _build_endpoint(phone_id: str) -> str:
    """Construit l'URL de l'endpoint Messages pour un phone_number_id donné."""
    return f"{META_GRAPH_BASE}/{META_API_VERSION}/{phone_id}/messages"


def _post(endpoint: str, token: str, payload: dict) -> dict:
    """
    Effectue l'appel HTTP POST vers l'API Meta et gère les erreurs proprement.

    :return: Réponse JSON de Meta, ou dict {"error": ...} en cas d'échec.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }
    try:
        response = requests.post(
            endpoint,
            headers=headers,
            data=json.dumps(payload),
            timeout=8,
        )
        data = response.json()

        if response.status_code == 200:
            msg_id = data.get("messages", [{}])[0].get("id", "?")
            logger.info("✅ Message envoyé → %s | message_id=%s", payload.get("to"), msg_id)
        else:
            error_detail = data.get("error", {})
            logger.error(
                "❌ Échec API Meta → %s | HTTP %s | code=%s | msg=%s",
                payload.get("to"),
                response.status_code,
                error_detail.get("code"),
                error_detail.get("message"),
            )

        return data

    except requests.exceptions.Timeout:
        logger.error("⏱️  Timeout lors de l'appel WhatsApp vers %s", payload.get("to"))
        return {"error": "timeout", "to": payload.get("to")}

    except Exception as exc:
        logger.error("💥 Erreur inattendue WhatsApp : %s", exc)
        return {"error": str(exc), "to": payload.get("to")}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MESSAGE INTERACTIF — MENU PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def send_interactive_menu(config: dict, customer_phone: str) -> dict:
    """
    Envoie un message WhatsApp interactif CTA URL au client :
      - Bouton : "Consulter le Menu 🍔" → ouvre menu_url

    Le token est résolu depuis WHATSAPP_ACCESS_TOKEN (System User Token).
    Le phone_number_id est résolu depuis config ou WHATSAPP_PHONE_NUMBER_ID.

    :param config:         Dict issu de supabase_tool.get_snack_config().
                           Champs utilisés : whatsapp_phone_number_id, menu_url, name.
    :param customer_phone: Numéro du client au format E.164 (ex: "+33785557054").
    :return:               Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _resolve_credentials(config)

    menu_url  = str(config.get("menu_url", "")).strip()
    nom_resto = str(config.get("nom_resto") or config.get("name", "Notre Snack")).strip()
    snack_id  = str(config.get("snack_id") or config.get("id", "")).strip()

    if not menu_url:
        logger.warning("menu_url absent pour snack '%s' — lien de fallback utilisé.", snack_id)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                customer_phone,
        "type":              "interactive",
        "interactive": {
            "type": "cta_url",
            "header": {
                "type": "text",
                "text": f"🍔 {nom_resto}",
            },
            "body": {
                "text": (
                    "Bonjour ! 👋\n"
                    "Votre commande a bien été reçue. "
                    "Consultez notre menu pour personnaliser votre choix."
                ),
            },
            "footer": {
                "text": "SnackFlow • Commande rapide via WhatsApp",
            },
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": "Consulter le Menu 🍔",
                    "url": menu_url or "https://le-menu.app",
                },
            },
        },
    }

    return _post(_build_endpoint(phone_id), token, payload)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MESSAGE DE FIDÉLITÉ — CLIENT LOYAL
# ═══════════════════════════════════════════════════════════════════════════════

def send_loyalty_welcome(config: dict, customer_phone: str) -> dict:
    """
    Envoie un message de bienvenue personnalisé aux clients fidèles.
    Déclenché lorsque total_orders >= loyalty_threshold.

    :param config:         Dict issu de supabase_tool.get_snack_config().
    :param customer_phone: Numéro du client au format E.164.
    :return:               Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _resolve_credentials(config)

    nom_resto = str(config.get("nom_resto") or config.get("name", "votre snack préféré")).strip()
    menu_url  = str(config.get("menu_url", "")).strip()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                customer_phone,
        "type":              "interactive",
        "interactive": {
            "type": "cta_url",
            "header": {
                "type": "text",
                "text": "⭐ Client Fidèle — Merci !",
            },
            "body": {
                "text": (
                    f"Ravi de vous revoir chez {nom_resto} ! 🎉\n\n"
                    "En tant que client fidèle, votre menu habituel est prêt "
                    "à être confirmé en un clic. Profitez-en !"
                ),
            },
            "footer": {
                "text": "SnackFlow • Programme Fidélité",
            },
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": "Accéder à mon menu 🍔",
                    "url": menu_url or "https://le-menu.app",
                },
            },
        },
    }

    return _post(_build_endpoint(phone_id), token, payload)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MESSAGE TEXTE SIMPLE — UTILITAIRE (fallback / alertes / RGPD)
# ═══════════════════════════════════════════════════════════════════════════════

def send_text_message(config: dict, customer_phone: str, body: str) -> dict:
    """
    Envoie un message texte simple (fallback, alertes, notices RGPD).

    :param config:         Dict issu de supabase_tool.get_snack_config().
    :param customer_phone: Destinataire au format E.164.
    :param body:           Texte du message (supporte le Markdown WhatsApp : *gras*, _italique_).
    :return:               Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _resolve_credentials(config)

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                customer_phone,
        "type":              "text",
        "text": {
            "preview_url": False,
            "body":        body,
        },
    }

    return _post(_build_endpoint(phone_id), token, payload)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. BOUTONS INTERACTIFS — VALIDATION GÉRANT
# ═══════════════════════════════════════════════════════════════════════════════

def send_interactive_buttons(
    config: dict,
    recipient_phone: str,
    body_text: str,
    buttons: list,
    header_text: str = "",
    footer_text: str = "",
) -> dict:
    """
    Envoie un message WhatsApp interactif à boutons quick_reply (max 3).

    :param config:          Dict issu de supabase_tool.get_snack_config().
    :param recipient_phone: Destinataire au format E.164.
    :param body_text:       Corps du message (texte principal).
    :param buttons:         Liste de dicts [{"id": "CONFIRM_<uuid>", "title": "✅ Valider"}, ...].
                            Max 3 boutons. Titres limités à 20 caractères (contrainte Meta).
    :param header_text:     (optionnel) Texte d'en-tête.
    :param footer_text:     (optionnel) Texte de pied de message.
    :return:                Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _resolve_credentials(config)

    if not buttons or len(buttons) > 3:
        logger.error("send_interactive_buttons : 1 à 3 boutons requis (reçu %d).", len(buttons))
        return {"error": "invalid_buttons_count"}

    formatted_buttons = [
        {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"][:20]}}
        for btn in buttons
    ]

    interactive: dict = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": formatted_buttons},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                recipient_phone,
        "type":              "interactive",
        "interactive":       interactive,
    }

    return _post(_build_endpoint(phone_id), token, payload)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LIST MESSAGE — MENU INTERACTIF (sélection produit)
# ═══════════════════════════════════════════════════════════════════════════════

def send_list_menu(
    config: dict,
    customer_phone: str,
    sections: list,
    body_text: str = "Choisissez un article :",
    button_text: str = "Voir le menu",
    header_text: str = "",
    footer_text: str = "",
) -> dict:
    """
    Envoie un message interactif de type 'list' (menu déroulant WhatsApp).

    Contraintes Meta :
      - button_text  : max 20 caractères
      - header_text  : max 60 caractères
      - sections[].title    : max 24 caractères
      - rows[].id           : max 200 caractères
      - rows[].title        : max 24 caractères
      - rows[].description  : max 72 caractères
      - Max 10 lignes au total toutes sections confondues

    :param config:          Dict issu de supabase_tool.get_snack_config().
    :param customer_phone:  Destinataire au format E.164.
    :param sections:        Liste de sections [{"title": "...", "rows": [{"id": "...", "title": "...", "description": "..."}]}].
    :param body_text:       Corps du message (obligatoire).
    :param button_text:     Libellé du bouton d'ouverture (max 20 chars).
    :param header_text:     En-tête optionnel (max 60 chars).
    :param footer_text:     Pied de message optionnel (max 60 chars).
    :return:                Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _resolve_credentials(config)

    if not sections:
        logger.error("send_list_menu : sections vides — envoi annulé.")
        return {"error": "empty_sections"}

    # Respect des limites Meta
    safe_sections = []
    total_rows = 0
    for section in sections:
        rows = []
        for row in section.get("rows", []):
            if total_rows >= 10:
                break
            rows.append({
                "id":          str(row.get("id", ""))[:200],
                "title":       str(row.get("title", ""))[:24],
                "description": str(row.get("description", ""))[:72],
            })
            total_rows += 1
        if rows:
            safe_sections.append({
                "title": str(section.get("title", "Menu"))[:24],
                "rows":  rows,
            })

    interactive: dict = {
        "type": "list",
        "body": {"text": body_text[:1024]},
        "action": {
            "button":   button_text[:20],
            "sections": safe_sections,
        },
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text[:60]}
    if footer_text:
        interactive["footer"] = {"text": footer_text[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                customer_phone,
        "type":              "interactive",
        "interactive":       interactive,
    }

    return _post(_build_endpoint(phone_id), token, payload)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TICKET CUISINE — NOTIFICATION RESTAURATEUR
# ═══════════════════════════════════════════════════════════════════════════════

def send_kitchen_ticket(config: dict, order_data: dict) -> dict:
    """
    Envoie un ticket de commande formaté au restaurateur via WhatsApp.

    Le destinataire est le numéro du restaurateur (resto_phone dans config).
    Ce message sert de bon de commande cuisine.

    Structure attendue de order_data ::

        {
            "customer_phone": "+33785557054",
            "items": [
                {"name": "Burger Montagnard", "qty": 2, "options": ["Sauce Algérienne"]},
                {"name": "Frites Maison",     "qty": 1}
            ],
            "total": "18.50",   # float ou str
            "notes": "Sans oignons"  # optionnel
        }

    :param config:     Dict issu de supabase_tool.get_snack_config().
                       Champ destinataire : resto_phone.
    :param order_data: Dict structuré de la commande.
    :return:           Réponse JSON de Meta ou dict d'erreur.
    """
    if "items" not in order_data or not isinstance(order_data["items"], list):
        raise ValueError("order_data doit contenir une clé 'items' de type list.")
    if "total" not in order_data:
        raise ValueError("order_data doit contenir une clé 'total'.")

    # ── Destinataire : le restaurateur ───────────────────────────────────────
    resto_phone = str(config.get("resto_phone", "")).strip()
    if not resto_phone:
        logger.error(
            "[%s] 'resto_phone' absent dans config — ticket cuisine non envoyé.",
            config.get("snack_id") or config.get("id", "?"),
        )
        return {"error": "resto_phone manquant dans config", "status": "not_sent"}

    # ── Formatage du ticket ───────────────────────────────────────────────────
    customer_phone = str(order_data.get("customer_phone", "Inconnu")).strip()
    items          = order_data["items"]
    total          = order_data["total"]
    notes          = str(order_data.get("notes", "")).strip()
    heure          = datetime.now().strftime("%H:%M")
    separateur     = "▬" * 10

    lignes_items = []
    for item in items:
        name     = str(item.get("name", "Article")).strip()
        qty      = str(item.get("qty", item.get("quantity", 1))).strip()
        options  = item.get("options", [])
        lignes_items.append(f"• {qty}x {name}")
        for opt in options:
            lignes_items.append(f"  ↳ {opt}")

    body_lines = [
        "📟 *NOUVELLE COMMANDE*",
        separateur,
        f"👤 *Client :* {customer_phone}",
        "🍔 *Détails :*",
        "\n".join(lignes_items),
        "",
        f"💰 Total : {total}€",
    ]

    if notes:
        body_lines += ["", f"📝 *Notes :* {notes}"]

    body_lines += [separateur, f"🕒 Heure : {heure}"]

    ticket_body = "\n".join(body_lines)

    logger.info(
        "🎫 Envoi ticket cuisine → %s | client=%s | total=%s€",
        resto_phone, customer_phone, total,
    )

    return send_text_message(config, resto_phone, ticket_body)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BLOC DE TEST RAPIDE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json as _json

    print("=" * 60)
    print("   SnackFlow — WhatsApp Tool v2.0 — Self-Test")
    print("   (System User Token depuis .env)")
    print("=" * 60)

    # Config de test simulée (normalement issue de supabase_tool.get_snack_config())
    MOCK_CONFIG = {
        "id":                        "uuid-snack-test-01",
        "name":                      "Le Snack du Coin",
        "whatsapp_phone_number_id":  os.getenv("WHATSAPP_PHONE_NUMBER_ID", "VOTRE_PHONE_NUMBER_ID"),
        "menu_url":                  "https://le-menu.app/snack-du-coin",
        "resto_phone":               "+33600000000",
        "loyalty_threshold":         5,
    }

    TEST_CUSTOMER = "+33785557054"   # ← à remplacer par un vrai numéro de test

    print(f"\n[1] Envoi du menu interactif à {TEST_CUSTOMER}...")
    r1 = send_interactive_menu(MOCK_CONFIG, TEST_CUSTOMER)
    print("   →", _json.dumps(r1, indent=4, ensure_ascii=False))

    print(f"\n[2] Envoi d'un message texte simple (fallback)...")
    r2 = send_text_message(MOCK_CONFIG, TEST_CUSTOMER, "⚠️ Test fallback SnackFlow v2.0.")
    print("   →", _json.dumps(r2, indent=4, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("   ✅ Self-Test terminé")
    print("=" * 60)
