"""
Layer 2 — Navigation : WhatsApp Webhook (SnackFlow v2.0 Full-WhatsApp)
======================================================================
Point d'entrée unique du système — api.menudirect.fr

Reçoit les messages WhatsApp entrants depuis Meta Graph API (payload réel),
parse le numéro expéditeur et le texte, puis orchestre de façon asynchrone :
  1. upsert_customer()       → Supabase CRM
  2. create_order()          → Supabase orders
  3. send_interactive_menu() → WhatsApp client (confirmation + menu)
  4. send_kitchen_ticket()   → WhatsApp snack (ticket cuisine)

Architecture v2.0 — System User Token :
  - Un seul token Meta (WHATSAPP_ACCESS_TOKEN) pour tous les tenants.
  - Authentification tenant via metadata.phone_number_id → table snacks.
  - phone_number_id inconnu → log NEW_ID_DETECTED + 200 (pas de retry Meta).

Behavioral Rules :
  - Réponse 202 immédiate à Meta (< 500 ms)
  - Traitement complet en arrière-plan (< 3 s)
  - Self-Healing : si Supabase ou WhatsApp échoue → log + continue
  - Formatage E.164 systématique
  - Zéro GSheets, zéro Twilio, zéro IVR, zéro SMS, zéro appel vocal
"""

import hashlib
import hmac
import logging
import os
import re
import threading
import time
import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from flask import Flask, request, jsonify
from dotenv import load_dotenv

# --- Import des Tools Layer 3 ---
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from layer3_tools.phone_tool import safe_normalize
from layer3_tools.whatsapp_tool import (
    send_interactive_menu,
    send_interactive_buttons,
    send_text_message,
)
from layer3_tools.supabase_tool import (
    get_snack_config,
    get_snack_by_phone_id,
    upsert_customer,
    delete_customer_data,
    create_order,
    update_order_status,
    get_order_by_id,
    health_check as supabase_health,
)
from layer3_tools.gemini_tool import parse_order_text
from layer3_tools.hubrise_tool import push_to_hubrise

load_dotenv()

app = Flask(__name__)
_logger = logging.getLogger("snack_flow.webhook")

# ─── Config ───────────────────────────────────────────────────────────────────

DEFAULT_SNACK_ID      = os.getenv("DEFAULT_SNACK_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET   = os.getenv("WHATSAPP_APP_SECRET", "")
ADMIN_API_KEY         = os.getenv("ADMIN_API_KEY", "")

if not WHATSAPP_APP_SECRET:
    _logger.warning(
        "⚠️  WHATSAPP_APP_SECRET non configuré — vérification de signature DÉSACTIVÉE. "
        "NE PAS utiliser en production sans cette variable."
    )

# ─── Thread pool (bounded) ────────────────────────────────────────────────────
_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="wa_worker")
atexit.register(lambda: _executor.shutdown(wait=True, cancel_futures=False))

# ─── Cache config restaurant (TTL 5 min) ──────────────────────────────────────

CACHE_TTL_SECONDS = 300
_config_cache: dict = {}
_cache_timestamps: dict = {}
_cache_lock = threading.Lock()


def _cache_get(snack_id: str) -> Optional[dict]:
    with _cache_lock:
        ts = _cache_timestamps.get(snack_id)
        if ts and (time.time() - ts) < CACHE_TTL_SECONDS:
            return _config_cache.get(snack_id)
        _config_cache.pop(snack_id, None)
        _cache_timestamps.pop(snack_id, None)
        return None


def _cache_set(snack_id: str, config: dict) -> None:
    with _cache_lock:
        _config_cache[snack_id] = config
        _cache_timestamps[snack_id] = time.time()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize(value: str, max_len: int = 512) -> str:
    """Retire les caractères dangereux et tronque."""
    cleaned = re.sub(r'[<>"\';&+%]', "", str(value))
    return cleaned[:max_len].strip()


def _redact(value: str, visible: int = 6) -> str:
    """Masque partiellement une valeur sensible pour les logs."""
    if not value or len(value) <= visible:
        return "***"
    return value[:visible] + "***"


def _load_config(snack_id: str) -> Optional[dict]:
    """Charge la config restaurant depuis le cache ou Supabase."""
    cached = _cache_get(snack_id)
    if cached is not None:
        return cached
    try:
        config = get_snack_config(snack_id)
        _cache_set(snack_id, config)
        return config
    except Exception as e:
        print(f"⚠️  Config introuvable pour snack_id='{snack_id}': {e}")
        return None


# =============================================================================
# RGPD — Helpers droits des personnes (Art. 13 & 17)
# =============================================================================

_DELETION_KEYWORDS = frozenset([
    "supprimer mes donnees",
    "supprime mes donnees",
    "effacer mes donnees",
    "delete my data",
    "droit effacement",
    "oubliez moi",
    "oublie moi",
])

_RGPD_NOTICE = (
    "ℹ️ *Vos données & RGPD*\n\n"
    "Votre numéro et vos commandes sont traités par *{nom_resto}* "
    "pour gérer votre relation client "
    "(base légale : exécution du contrat — Art. 6(1)(b) RGPD).\n\n"
    "📅 Conservation : 3 ans maximum.\n"
    "🔐 Droits : accès, rectification, suppression.\n\n"
    "Pour effacer vos données, répondez :\n"
    "*SUPPRIMER MES DONNÉES*"
)

_DELETION_CONFIRM = (
    "✅ Vos données ont bien été supprimées de nos systèmes.\n"
    "Aucune information vous concernant n'est conservée chez *{nom_resto}*.\n\n"
    "Merci de votre confiance."
)


def _normalize_for_match(text: str) -> str:
    """Normalise le texte pour matching insensible aux accents/casse."""
    return (
        text.lower()
        .replace("é", "e").replace("è", "e").replace("ê", "e").replace("ë", "e")
        .replace("à", "a").replace("â", "a")
        .replace("ô", "o").replace("î", "i")
        .replace("ù", "u").replace("û", "u")
        .replace("ç", "c")
        .replace("\u2019", " ").replace("'", " ").replace("-", " ")
    )


def _is_deletion_request(text: str) -> bool:
    """Détecte une demande RGPD d'effacement dans le message client."""
    normalized = _normalize_for_match(text)
    return any(kw in normalized for kw in _DELETION_KEYWORDS)


def _send_rgpd_notice(config: dict, customer_phone: str, nom_resto: str) -> None:
    """Envoie la notice d'information RGPD Art. 13 au premier contact client."""
    body = _RGPD_NOTICE.format(nom_resto=nom_resto)
    result = send_text_message(config, customer_phone, body)
    if "error" not in result:
        _logger.info("✅ Notice RGPD Art. 13 envoyée → %s", _redact(customer_phone))
    else:
        _logger.warning("⚠️  Notice RGPD échouée : %s", result.get("error"))


def _handle_deletion_request(config: dict, snack_id: str, customer_phone: str) -> None:
    """
    Traite une demande d'effacement RGPD Art. 17.
    Supprime toutes les données du client et envoie une confirmation WhatsApp.
    """
    _logger.info("🗑️  [RGPD] Demande d'effacement | %s", _redact(customer_phone))
    result   = delete_customer_data(phone_e164=customer_phone, snack_id=snack_id)
    nom_resto = config.get("nom_resto") or config.get("name", "Notre Snack")

    if result.get("status") == "deleted":
        body = _DELETION_CONFIRM.format(nom_resto=nom_resto)
        _logger.info(
            "✅ [RGPD] Données supprimées | phone=%s | orders=%d",
            _redact(customer_phone), result.get("orders_deleted", 0),
        )
    else:
        body = (
            "⚠️ Une erreur est survenue lors de la suppression de vos données. "
            "Veuillez contacter directement le restaurant."
        )
        _logger.error("❌ [RGPD] Échec suppression : %s", result.get("message"))

    send_text_message(config, customer_phone, body)


# =============================================================================
# PARSING DU PAYLOAD META WHATSAPP (format réel Cloud API)
# =============================================================================

def _parse_whatsapp_payload(data: dict) -> Optional[dict]:
    """
    Parse le payload réel envoyé par Meta WhatsApp Cloud API.

    Structure attendue :
    {
      "entry": [{
        "changes": [{
          "value": {
            "messages": [{
              "from": "33785557054",
              "type": "text",
              "text": { "body": "Je veux commander un burger" }
            }],
            "metadata": { "phone_number_id": "..." }
          }
        }]
      }]
    }

    :return: dict {
                 "from_phone":      str,
                 "message_text":    str,
                 "message_type":    str,
                 "phone_number_id": str   ← identifiant Meta du numéro WA du snack
             }
             ou None si le payload ne contient pas de message texte exploitable.
    """
    try:
        entry   = data.get("entry", [])
        if not entry:
            return None

        changes = entry[0].get("changes", [])
        if not changes:
            return None

        value    = changes[0].get("value", {})

        # ── Extraction du phone_number_id (authentification tenant) ──────────
        metadata         = value.get("metadata", {})
        phone_number_id  = metadata.get("phone_number_id", "").strip()

        messages = value.get("messages", [])
        if not messages:
            # Peut être un statut de livraison (status update) — on ignore
            return None

        msg          = messages[0]
        from_phone   = msg.get("from", "")          # Format : "33785557054" (sans +)
        message_type = msg.get("type", "text")       # "text" | "interactive" | "image"...
        message_text = ""

        button_id = ""
        if message_type == "text":
            message_text = msg.get("text", {}).get("body", "").strip()
        elif message_type == "interactive":
            # Bouton reply ou list reply
            interactive = msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                button_reply = interactive.get("button_reply", {})
                message_text = button_reply.get("title", "")
                button_id    = button_reply.get("id", "")
            elif interactive.get("type") == "list_reply":
                message_text = interactive.get("list_reply", {}).get("title", "")
        else:
            # Type non géré (image, audio, etc.) — on log mais on ne crash pas
            message_text = f"[{message_type}]"

        if not from_phone:
            return None

        # Normalisation E.164 : Meta envoie sans le "+"
        if not from_phone.startswith("+"):
            from_phone = "+" + from_phone

        return {
            "from_phone":      safe_normalize(from_phone) or from_phone,
            "message_text":    _sanitize(message_text, max_len=1024),
            "message_type":    message_type,
            "phone_number_id": phone_number_id,
            "button_id":       button_id,
        }

    except Exception as e:
        print(f"❌ Erreur parsing payload WhatsApp : {e}")
        return None


# =============================================================================
# ROUTE 0 : GET /webhook — Vérification Meta
# =============================================================================

@app.route("/webhook", methods=["GET"])
def whatsapp_verify():
    """
    Endpoint de vérification Meta WhatsApp Business.
    Meta envoie hub.mode, hub.verify_token, hub.challenge.
    On renvoie hub.challenge si le token correspond.
    """
    mode      = request.args.get("hub.mode", "")
    token     = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        print(f"✅ Webhook vérifié par Meta — challenge={challenge}")
        return challenge, 200

    print(f"❌ Vérification échouée | token reçu='{token}'")
    return jsonify({"error": "Forbidden — token invalide"}), 403


# =============================================================================
# ROUTE 1 : POST /webhook — Messages WhatsApp entrants
# =============================================================================

def _verify_meta_signature() -> bool:
    """
    Vérifie la signature X-Hub-Signature-256 envoyée par Meta.
    Retourne True si la signature est valide OU si WHATSAPP_APP_SECRET n'est pas configuré
    ET que l'environnement n'est pas la production (mode dev uniquement).
    Voir : https://developers.facebook.com/docs/messenger-platform/webhooks#validate-payloads
    """
    if not WHATSAPP_APP_SECRET:
        # Fail-closed by default: only allow bypass in explicitly registered dev/test envs
        _env = os.getenv("FLASK_ENV", "production").lower()
        if _env not in ("development", "testing"):
            _logger.error(
                "🚫 WHATSAPP_APP_SECRET non configuré — requête rejetée. "
                "Définissez FLASK_ENV=development dans .env pour activer le bypass local."
            )
            return False
        # Dev/test bypass : let the request through with a warning
        _logger.warning(
            "⚠️  Signature DÉSACTIVÉE (FLASK_ENV=%s). Ne jamais utiliser en production.", _env
        )
        return True

    sig_header = request.headers.get("X-Hub-Signature-256", "")
    if not sig_header.startswith("sha256="):
        return False

    expected = hmac.HMAC(
        WHATSAPP_APP_SECRET.encode("utf-8"),
        request.data,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig_header[7:], expected)


@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    """
    Reçoit et traite les messages WhatsApp entrants (payload réel Meta).

    Répond 202 immédiatement à Meta pour éviter les retries.
    Le traitement réel (Supabase + WA) se fait dans un thread séparé.
    """
    # ── Vérification signature Meta (HMAC-SHA256) ────────────────────────────
    if not _verify_meta_signature():
        print("🚫 [WEBHOOK] Signature X-Hub-Signature-256 invalide — requête rejetée.")
        return jsonify({"error": "Invalid signature"}), 403

    data = request.get_json(force=True, silent=True) or {}

    # Parsing du payload Meta réel
    parsed = _parse_whatsapp_payload(data)

    if not parsed:
        # Peut être un événement "read receipt" ou "status" — on accepte silencieusement
        return jsonify({"status": "ignored"}), 200

    from_phone      = parsed["from_phone"]
    message_text    = parsed["message_text"]
    message_type    = parsed["message_type"]
    phone_number_id = parsed.get("phone_number_id", "")
    button_id       = parsed.get("button_id", "")

    # ── Authentification Multi-Tenant ────────────────────────────────────────
    # Chaque requête Meta porte metadata.phone_number_id.
    # On vérifie dans Supabase (table snacks) que l'ID correspond à un tenant actif.
    if not phone_number_id:
        # Aucun phone_number_id dans le payload → payload malformé, on ignore silencieusement
        _logger.warning("⚠️  Payload reçu sans phone_number_id — ignoré.")
        return jsonify({"status": "ignored", "reason": "missing phone_number_id"}), 200

    snack_record = get_snack_by_phone_id(phone_number_id)

    if not snack_record:
        # ID inconnu : on logue pour faciliter l'onboarding, mais on répond 200
        # pour éviter les retries Meta qui saturationnerait le webhook.
        _logger.warning(
            "🆕 [NEW_ID_DETECTED] phone_number_id='%s' inconnu dans Supabase. "
            "Enregistrez ce snack via register_restaurant() pour l'activer.",
            phone_number_id,
        )
        print(f"🆕 [NEW_ID_DETECTED] phone_number_id={phone_number_id}")
        return jsonify({
            "status": "ignored",
            "reason": "NEW_ID_DETECTED",
            "phone_number_id": phone_number_id,
        }), 200

    # Snack authentifié : UUID Supabase (schéma v3)
    snack_id   = snack_record.get("id") or DEFAULT_SNACK_ID
    snack_name = snack_record.get("name", snack_id)
    _logger.info("[ROUTING][SUCCESS] Tenant identifié : %s", snack_name)
    print(
        f"\n📲 Webhook [TENANT:{snack_name}] | phone_id={_redact(phone_number_id)} "
        f"| from={_redact(from_phone)} | type={message_type} | msg='{message_text[:50]}'"
    )

    # Traitement asynchrone — réponse 202 immédiate à Meta
    _executor.submit(_process_message, snack_id, from_phone, message_text, message_type, button_id)

    return jsonify({"status": "accepted"}), 202


# =============================================================================
# TRAITEMENT ASYNCHRONE — Orchestration principale
# =============================================================================

def _process_message(
    snack_id: str,
    from_phone: str,
    message_text: str,
    message_type: str,
    button_id: str = "",
):
    """
    Point d'entrée du traitement asynchrone.
    Route vers :
      - _handle_manager_callback() si le message vient du gérant et porte un button_id de validation
      - _process_new_order() pour toute autre commande client
    """
    config = _load_config(snack_id)
    if not config:
        print(f"❌ [PROCESS] Config snack '{snack_id}' introuvable — abandon.")
        return

    resto_phone = str(config.get("resto_phone", "")).strip()
    _MANAGER_PREFIXES = ("CONFIRM_", "REJECT_", "CALL_")

    if (
        button_id
        and resto_phone
        and from_phone == resto_phone
        and any(button_id.startswith(p) for p in _MANAGER_PREFIXES)
    ):
        _handle_manager_callback(button_id, from_phone, config, snack_id)
    else:
        _process_new_order(snack_id, from_phone, message_text, message_type, config)


def _handle_manager_callback(
    button_id: str,
    manager_phone: str,
    config: dict,
    snack_id: str,
):
    """
    Traite la réponse du gérant à un bouton de validation.

    button_id format : "<ACTION>_<order_uuid>"
      - CONFIRM_<uuid> → confirme + push HubRise + notifie client
      - REJECT_<uuid>  → annule + notifie client
      - CALL_<uuid>    → envoie le lien d'appel au gérant (wa.me)
    """
    try:
        action, order_id = button_id.split("_", 1)
    except ValueError:
        print(f"⚠️  [CALLBACK] button_id malformé : '{button_id}'")
        return

    print(f"\n🎛️  [CALLBACK] action={action} | order_id={order_id} | gérant={_redact(manager_phone)}")

    order = get_order_by_id(order_id, snack_id)
    if not order:
        print(f"❌ [CALLBACK] Commande introuvable : {order_id}")
        send_text_message(config, manager_phone, f"❌ Commande introuvable (id: {order_id[:8]}…)")
        return

    customer_phone = order.get("customer_phone", "")
    items          = order.get("items", [])
    nom_resto      = config.get("nom_resto") or config.get("name", "Le Snack")

    if action == "CONFIRM":
        # Mise à jour Supabase
        update_order_status(order_id=order_id, status="confirmed", snack_id=snack_id)
        # Push HubRise
        hubrise_result = push_to_hubrise(order, config)
        hubrise_ok     = "error" not in hubrise_result and not hubrise_result.get("skipped")
        # Notification client
        items_txt = "\n".join(
            f"  • {it.get('qty', 1)}x {it.get('name', '?')}" for it in items
        )
        send_text_message(
            config, customer_phone,
            f"✅ *Votre commande est confirmée !*\n\n{items_txt}\n\n"
            f"Merci de votre confiance chez _{nom_resto}_ 🙏",
        )
        print(f"✅ [CALLBACK] CONFIRM | order={order_id[:8]} | HubRise={'ok' if hubrise_ok else 'skipped/err'}")

    elif action == "REJECT":
        update_order_status(order_id=order_id, status="cancelled", snack_id=snack_id)
        send_text_message(
            config, customer_phone,
            f"😔 Désolé, votre commande n'a pas pu être traitée par _{nom_resto}_.\n"
            "N'hésitez pas à recommander ou à nous appeler directement.",
        )
        print(f"✅ [CALLBACK] REJECT | order={order_id[:8]}")

    elif action == "CALL":
        phone_link = customer_phone.lstrip("+")
        send_text_message(
            config, manager_phone,
            f"📞 *Appeler le client :*\n{customer_phone}\n\n"
            f"Lien direct : wa.me/{phone_link}\nTel : tel:{customer_phone}",
        )
        print(f"✅ [CALLBACK] CALL | order={order_id[:8]} | client={_redact(customer_phone)}")

    else:
        print(f"⚠️  [CALLBACK] Action inconnue : '{action}'")


def _process_new_order(
    snack_id: str,
    from_phone: str,
    message_text: str,
    message_type: str,
    config: dict,
):
    """
    Orchestre le traitement complet d'une nouvelle commande client :
      1. Détection RGPD
      2. Upsert customer CRM
      3. Notice RGPD Art. 13 (premier contact)
      4. Parsing LLM Gemini → items JSONB
      5. Création commande Supabase (status=pending)
      6. Confirmation WhatsApp → client (menu CTA)
      7. Boutons de validation → gérant (CONFIRM / REJECT / CALL)
    """
    print(f"\n🔄 [ORDER] Démarrage | {snack_id} | {_redact(from_phone)}")
    start_time = time.time()

    # ── Détection demande RGPD (effacement Art. 17) ──────────────────────────
    if message_type == "text" and _is_deletion_request(message_text):
        _handle_deletion_request(config, snack_id, from_phone)
        return

    # ── Étape 1 : Upsert customer CRM ────────────────────────────────────────
    is_new_customer = False
    try:
        customer_data   = upsert_customer(phone_e164=from_phone, snack_id=snack_id)
        is_new_customer = isinstance(customer_data, dict) and customer_data.get("total_orders", 0) == 1
        print(f"✅ [ORDER] Customer CRM upserted | nouveau={is_new_customer}")
    except Exception as e:
        print(f"⚠️  [ORDER] upsert_customer échoué (non bloquant) : {e}")

    if is_new_customer:
        try:
            nom_resto = config.get("nom_resto") or config.get("name", "Notre Snack")
            _send_rgpd_notice(config, from_phone, nom_resto)
        except Exception as e:
            print(f"⚠️  [ORDER] Notice RGPD échouée (non bloquant) : {e}")

    # ── Étape 2 : Parsing LLM (Gemini) → items JSONB ────────────────────────
    parsed_items = []
    if message_type == "text" and message_text:
        try:
            parsed_items = parse_order_text(message_text)
            print(f"✅ [ORDER] Gemini : {len(parsed_items)} article(s) → {parsed_items}")
        except Exception as e:
            print(f"⚠️  [ORDER] Gemini parse échoué : {e}")

    # ── Étape 3 : Création commande (status=pending) ─────────────────────────
    order_id: Optional[str] = None
    try:
        order_result = create_order(
            snack_id=snack_id,
            data={
                "customer_phone": from_phone,
                "items": parsed_items or [{"name": message_text or f"[{message_type}]", "qty": 1}],
                "status": "pending",
            },
        )
        order_id = order_result.get("row", {}).get("id")
        print(f"✅ [ORDER] Commande créée (id={order_id})")
    except Exception as e:
        print(f"⚠️  [ORDER] create_order échoué : {e}")

    # ── Étape 4 : Confirmation WhatsApp → Client ──────────────────────────────
    try:
        wa_result = send_interactive_menu(config, from_phone)
        if "error" not in wa_result:
            print(f"✅ [ORDER] Menu WA envoyé → {_redact(from_phone)}")
        else:
            print(f"❌ [ORDER] Échec envoi menu WA : {wa_result.get('error')}")
    except Exception as e:
        print(f"❌ [ORDER] Erreur envoi WA client : {e}")

    # ── Étape 5 : Boutons de validation → Gérant ─────────────────────────────
    resto_phone = str(config.get("resto_phone", "")).strip()
    if order_id and resto_phone:
        try:
            items_txt = "\n".join(
                f"  • {it.get('qty', 1)}x {it.get('name', '?')}"
                for it in (parsed_items or [{"name": message_text, "qty": 1}])
            )
            send_interactive_buttons(
                config=config,
                recipient_phone=resto_phone,
                header_text="🆕 Nouvelle commande",
                body_text=(
                    f"Client : {from_phone}\n\n"
                    f"{items_txt}\n\n"
                    f"ID : {order_id[:8]}…"
                ),
                footer_text="SnackFlow • Validation requise",
                buttons=[
                    {"id": f"CONFIRM_{order_id}", "title": "✅ Valider"},
                    {"id": f"REJECT_{order_id}",  "title": "❌ Refuser"},
                    {"id": f"CALL_{order_id}",    "title": "📞 Appeler"},
                ],
            )
            print(f"✅ [ORDER] Boutons validation envoyés → gérant ({_redact(resto_phone)})")
        except Exception as e:
            print(f"⚠️  [ORDER] Boutons validation échoués : {e}")
    else:
        print("⚠️  [ORDER] resto_phone absent — boutons validation non envoyés.")

    elapsed = round(time.time() - start_time, 2)
    print(f"✅ [ORDER] Terminé en {elapsed}s\n")


# =============================================================================
# ROUTE 2 : POST /admin/gdpr/delete — Suppression RGPD (admin)
# =============================================================================

@app.route("/admin/gdpr/delete", methods=["POST"])
def admin_gdpr_delete():
    """
    Endpoint admin RGPD : suppression manuelle des données d'un client (Art. 17).

    Requiert : Authorization: Bearer <ADMIN_API_KEY>
    Body JSON : { "phone_e164": "+33612345678", "snack_id": "uuid-du-snack" }
    """
    if not ADMIN_API_KEY:
        return jsonify({"error": "Endpoint désactivé (ADMIN_API_KEY non configuré)"}), 503

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or not hmac.compare_digest(
        auth_header[7:], ADMIN_API_KEY
    ):
        _logger.warning("🚫 [ADMIN] Accès non autorisé /admin/gdpr/delete")
        return jsonify({"error": "Unauthorized"}), 401

    body     = request.get_json(silent=True) or {}
    phone    = body.get("phone_e164", "").strip()
    snack_id = body.get("snack_id",   "").strip()

    if not phone or not snack_id:
        return jsonify({"error": "phone_e164 et snack_id sont requis"}), 400

    result = delete_customer_data(phone_e164=phone, snack_id=snack_id)
    return jsonify(result), 200 if result.get("status") == "deleted" else 500


# =============================================================================
# ROUTE 3 : GET /health — Health check
# =============================================================================

@app.route("/health", methods=["GET"])
def health_check():
    """Vérifie que le serveur et Supabase sont opérationnels."""
    supabase_status = supabase_health()
    return jsonify({
        "status":   "ok",
        "service":  "Snack-Flow WhatsApp Webhook",
        "version":  "2.0",
        "supabase": supabase_status,
    }), 200


# =============================================================================
# DÉMARRAGE DIRECT
# =============================================================================

if __name__ == "__main__":
    print("🚀 Snack-Flow v2.0 — WhatsApp Webhook — Démarrage Layer 2")
    print("━" * 55)

    REQUIRED_VARS = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_VERIFY_TOKEN",
        "DEFAULT_SNACK_ID",
    ]
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        print(f"⚠️  Variables .env manquantes : {missing}")
    else:
        print("✅ Toutes les variables critiques sont présentes")

    port = int(os.getenv("PORT", os.getenv("SERVER_PORT", 5001)))
    print(f"✅ Webhook prêt — En écoute sur http://0.0.0.0:{port}")
    print("   Routes disponibles :")
    print("   - POST /webhook → Message WhatsApp entrant (payload Meta réel)")
    print("   - GET  /webhook → Vérification Meta (hub.challenge)")
    print("   - GET  /health  → Health check")
    print("━" * 55)

    app.run(host="0.0.0.0", port=port, debug=False)
