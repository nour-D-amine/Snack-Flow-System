"""
whatsapp_tool.py — Snack-Flow WhatsApp Layer (Multi-Tenant)
============================================================
Intègre l'API Cloud officielle de Meta pour l'envoi de messages
interactifs à boutons (CTA URL + phone_number).

Principes :
  - Zéro clé en dur : tout passe par l'argument `config` (dict GSheets).
  - Self-Healing  : les erreurs API sont loguées sans faire planter le flux.
  - Multi-Tenant  : chaque appel utilise le token + phone_id du tenant concerné.
  - Vitesse       : appels HTTP synchrones légers (< 1 s hors latence réseau).

Fonctions publiques :
  - send_interactive_menu(config, customer_phone)       → dict
  - send_loyalty_welcome(config, customer_phone)        → dict
  - send_kitchen_ticket(config, order_data)             → dict
  - send_text_message(config, customer_phone, body)     → dict  [utilitaire interne]
"""

import json
import logging
from datetime import datetime
import requests

# ─── Logger dédié (n'interfère pas avec le logger racine) ─────────────────────

logger = logging.getLogger("snack_flow.whatsapp")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s | whatsapp_tool | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ─── Constante versionnée ─────────────────────────────────────────────────────

META_API_VERSION = "v19.0"
META_GRAPH_BASE  = "https://graph.facebook.com"


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNES
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_config(config: dict) -> tuple[str, str]:
    """
    Extrait et valide les champs obligatoires du dictionnaire config.

    :param config: Dict issu de get_snack_config() (GSheets).
    :return:       (whatsapp_phone_id, whatsapp_token)
    :raises ValueError: Si un champ obligatoire est absent ou vide.
    """
    phone_id = str(config.get("whatsapp_phone_id", "")).strip()
    token    = str(config.get("whatsapp_token",    "")).strip()

    if not phone_id:
        raise ValueError(
            f"[{config.get('snack_id', '?')}] 'whatsapp_phone_id' manquant dans config."
        )
    if not token:
        raise ValueError(
            f"[{config.get('snack_id', '?')}] 'whatsapp_token' manquant dans config."
        )
    return phone_id, token


def _build_endpoint(phone_id: str) -> str:
    """Construit l'URL de l'endpoint Messages pour un tenant donné."""
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
            timeout=8,  # garde-fou < 3 s dans le flux principal
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
    Envoie un message WhatsApp interactif à deux boutons CTA :
      - Bouton 1 : "Consulter le Menu 🍔"  → ouvre menu_url (type url)
      - Bouton 2 : "Appeler le Snack 📞"   → compose le numéro du resto (type phone_number)

    Le payload utilise le format `interactive > cta_url` et `interactive > button`
    conformes à l'API Cloud de Meta (v19.0).

    :param config:         Dict complet issu de get_snack_config().
                           Champs requis : whatsapp_phone_id, whatsapp_token,
                                          menu_url, nom_resto, snack_id.
    :param customer_phone: Numéro du client au format E.164 (ex: "+33785557054").
    :return:               Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _validate_config(config)

    menu_url   = str(config.get("menu_url",   "")).strip()
    nom_resto  = str(config.get("nom_resto",  "Notre Snack")).strip()
    snack_id   = str(config.get("snack_id",   "")).strip()
    # Numéro du resto : on extrait depuis config
    resto_phone = str(config.get("resto_phone", "")).strip()

    if not menu_url:
        logger.warning("menu_url absent pour %s — bouton Menu désactivé.", config.get("snack_id"))

    # ── Corps du message interactif ──────────────────────────────────────────
    # Meta supporte deux types CTA : url et phone_number.
    # On utilise le type `cta_url` pour le bouton menu
    # et un deuxième message `phone_number` si le numéro resto est disponible.
    #
    # ⚠️  L'API Cloud Meta ne supporte pas de mixer url + phone_number dans
    #     un seul bloc `buttons`. On envoie donc un message de type `cta_url`
    #     (bouton URL) enrichi d'un footer avec le numéro, puis un second bouton
    #     `reply` invitant à appeler — pattern recommandé par Meta pour les PME.

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
                    "Commandez facilement en ligne ou contactez-nous directement."
                ),
            },
            "footer": {
                "text": f"📞 {resto_phone}" if resto_phone else "Snack-Flow • Commande rapide",
            },
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": "Consulter le Menu 🍔",
                    "url": menu_url or "https://snackflow.app",
                },
            },
        },
    }

    result = _post(_build_endpoint(phone_id), token, payload)

    # ── Second message : bouton "Appeler" si numéro disponible ───────────────
    if resto_phone and "error" not in result:
        call_payload = {
            "messaging_product": "whatsapp",
            "recipient_type":    "individual",
            "to":                customer_phone,
            "type":              "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": "Vous préférez parler à quelqu'un ? 🤙",
                },
                "action": {
                    "buttons": [
                        {
                            "type":  "reply",
                            "reply": {
                                "id":    f"{snack_id}|call_resto",
                                "title": "Appeler le Snack 📞",
                            },
                        }
                    ]
                },
                "footer": {
                    "text": resto_phone,
                },
            },
        }
        _post(_build_endpoint(phone_id), token, call_payload)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MESSAGE DE FIDÉLITÉ — CLIENT LOYAL
# ═══════════════════════════════════════════════════════════════════════════════

def send_loyalty_welcome(config: dict, customer_phone: str) -> dict:
    """
    Envoie un message de bienvenue personnalisé aux clients LOYAL.
    Ce message est déclenché lorsque check_customer_loyalty() retourne "LOYAL".

    :param config:         Dict complet issu de get_snack_config().
    :param customer_phone: Numéro du client au format E.164.
    :return:               Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _validate_config(config)

    nom_resto  = str(config.get("nom_resto", "votre snack préféré")).strip()
    menu_url   = str(config.get("menu_url",  "")).strip()

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
                "text": "Snack-Flow • Programme Fidélité",
            },
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": "Accéder à mon menu 🍔",
                    "url": menu_url or "https://snackflow.app",
                },
            },
        },
    }

    return _post(_build_endpoint(phone_id), token, payload)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MESSAGE TEXTE SIMPLE — UTILITAIRE (fallback / alertes internes)
# ═══════════════════════════════════════════════════════════════════════════════

def send_text_message(config: dict, customer_phone: str, body: str) -> dict:
    """
    Envoie un message texte simple (fallback ou alerte interne).
    Utilisé notamment pour les notifications d'échec vers le restaurateur.

    :param config:         Dict complet issu de get_snack_config().
    :param customer_phone: Destinataire au format E.164.
    :param body:           Texte du message.
    :return:               Réponse JSON de Meta ou dict d'erreur.
    """
    phone_id, token = _validate_config(config)

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
# 4. TICKET CUISINE — NOTIFICATION RESTAURATEUR
# ═══════════════════════════════════════════════════════════════════════════════

def send_kitchen_ticket(config: dict, order_data: dict) -> dict:
    """
    Envoie un ticket de commande formaté au restaurateur via WhatsApp.

    Le destinataire est le numéro du restaurateur lui-même (resto_phone dans
    config), PAS le client. Ce message sert de bon de commande cuisine.

    Structure attendue de order_data ::

        {
            "customer_phone": "+33785557054",
            "items": [
                {
                    "name":     "Burger Montagnard",
                    "quantity": 1,
                    "options":  ["Sauce Algérienne"]   # optionnel
                },
                {
                    "name":     "Frites Maison",
                    "quantity": 1
                }
            ],
            "total":   18.50,       # float ou str
            "notes":   "Sans oignons"  # optionnel
        }

    Format de sortie WhatsApp ::

        📟 *NOUVELLE COMMANDE*
        ▬▬▬▬▬▬▬▬▬▬
        👤 *Client :* +33785557054
        🍔 *Détails :*
        • 1x Burger Montagnard
          ↳ Sauce Algérienne
        • 1x Frites Maison
        • 1x Coca-Cola 33cl

        💰 Total : 18.50€
        ▬▬▬▬▬▬▬▬▬▬
        🕒 Heure : 14:10

    :param config:     Dict complet issu de get_snack_config().
                       Champs requis : whatsapp_phone_id, whatsapp_token.
                       Champ utilisé comme destinataire : resto_phone.
    :param order_data: Dict structuré de la commande (voir ci-dessus).
    :return:           Réponse JSON de Meta ou dict d'erreur.
    :raises ValueError: Si 'items' ou 'total' sont absents de order_data.
    """
    # ── Validation des champs obligatoires de order_data ────────────────────
    if "items" not in order_data or not isinstance(order_data["items"], list):
        raise ValueError("order_data doit contenir une clé 'items' de type list.")
    if "total" not in order_data:
        raise ValueError("order_data doit contenir une clé 'total'.")

    # ── Destinataire : le restaurateur lui-même ──────────────────────────────
    resto_phone = str(config.get("resto_phone", "")).strip()
    if not resto_phone:
        logger.error(
            "[%s] 'resto_phone' absent dans config — ticket cuisine non envoyé.",
            config.get("snack_id", "?"),
        )
        return {"error": "resto_phone manquant dans config", "status": "not_sent"}

    # ── Formatage du corps du ticket ─────────────────────────────────────────
    customer_phone = str(order_data.get("customer_phone", "Inconnu")).strip()
    items          = order_data["items"]
    total          = order_data["total"]
    notes          = str(order_data.get("notes", "")).strip()
    heure          = datetime.now().strftime("%H:%M")
    separateur     = "▬" * 10

    # Construction des lignes d'articles
    lignes_items = []
    for item in items:
        name     = str(item.get("name",     "Article")).strip()
        quantity = str(item.get("quantity", 1)).strip()
        options  = item.get("options", [])

        ligne = f"• {quantity}x {name}"
        lignes_items.append(ligne)

        # Options en retrait (une par ligne)
        for opt in options:
            lignes_items.append(f"  ↳ {opt}")

    details_str = "\n".join(lignes_items)

    # Corps principal
    body_lines = [
        f"📟 *NOUVELLE COMMANDE*",
        separateur,
        f"👤 *Client :* {customer_phone}",
        f"🍔 *Détails :*",
        details_str,
        "",
        f"💰 Total : {total}€",
    ]

    # Section notes (facultative)
    if notes:
        body_lines.append("")
        body_lines.append(f"📝 *Notes :* {notes}")

    body_lines += [
        separateur,
        f"🕒 Heure : {heure}",
    ]

    ticket_body = "\n".join(body_lines)

    logger.info(
        "🎫 Envoi ticket cuisine → %s | client=%s | total=%s€",
        resto_phone, customer_phone, total,
    )

    # ── Envoi via send_text_message (réutilise _post + gestion erreurs) ──────
    return send_text_message(config, resto_phone, ticket_body)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BLOC DE TEST RAPIDE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json as _json

    print("=" * 60)
    print("   Snack-Flow — WhatsApp Tool Multi-Tenant — Self-Test")
    print("=" * 60)

    # Config de test simulée (normalement issue de get_snack_config())
    MOCK_CONFIG = {
        "snack_id":            "SNACK_TEST_01",
        "nom_resto":           "Le Snack du Coin",
        "whatsapp_phone_id":   "VOTRE_PHONE_NUMBER_ID",   # ← à remplacer
        "whatsapp_token":      "VOTRE_ACCESS_TOKEN",       # ← à remplacer
        "menu_url":            "https://snackflow.app/menu/snack-test-01",
        "resto_phone":         "+33600000000",
        "loyalty_threshold":   3,
    }

    TEST_CUSTOMER = "+33785557054"   # ← à remplacer par un vrai numéro de test

    print(f"\n[1] Envoi du menu interactif à {TEST_CUSTOMER}...")
    r1 = send_interactive_menu(MOCK_CONFIG, TEST_CUSTOMER)
    print("   →", _json.dumps(r1, indent=4, ensure_ascii=False))

    print(f"\n[2] Envoi du message fidélité à {TEST_CUSTOMER}...")
    r2 = send_loyalty_welcome(MOCK_CONFIG, TEST_CUSTOMER)
    print("   →", _json.dumps(r2, indent=4, ensure_ascii=False))

    print(f"\n[3] Envoi d'un message texte simple (fallback)...")
    r3 = send_text_message(MOCK_CONFIG, TEST_CUSTOMER, "⚠️ Test fallback Snack-Flow.")
    print("   →", _json.dumps(r3, indent=4, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("   ✅ Self-Test terminé")
    print("=" * 60)
