"""
Layer 2 — Navigation : IVR Flow (Snack-Flow)
=============================================
Ce module est le CERVEAU du système.
Il reçoit les appels entrants WhatsApp Business, présente le menu interactif,
puis orchestre :
  - [Option 1] L'envoi du menu interactif WhatsApp au client + ticket cuisine resto
  - [Option 2] Notification directe au restaurant pour rappel manuel
  - Le log Google Sheets (onglet COMMANDES) + CRM client

Architecture : Webhook Flask → Orchestration asynchrone MULTI-TENANT
Behavioral Rules :
  - Routing par snack_id → chargement du contexte restaurant (GSheets RESTOS)
  - Formatage E.164 systématique (phone_tool)
  - Self-Healing : si WhatsApp échoue → log GSheets de l'échec
  - Data-First : log GSheets avant tout retour client
  - Vitesse < 3 secondes (exécution en arrière-plan)
"""

import os
import re
import time
import threading
from typing import Optional
from flask import Flask, request, Response, jsonify
from dotenv import load_dotenv

# --- Import des Tools Layer 3 ---
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from layer3_tools.phone_tool import safe_normalize
from layer3_tools.whatsapp_tool import (
    send_interactive_menu,
    send_loyalty_welcome,
    send_kitchen_ticket,
    send_text_message,
)
from layer3_tools.gsheets_tool import (
    get_snack_config,
    log_order,
    check_customer_loyalty,
)
from layer3_tools.crm_tool import initialize_db, upsert_client, log_interaction

load_dotenv()

app = Flask(__name__)

# --- Fallback snack_id (dev / mono-restaurant) ---
DEFAULT_SNACK_ID = os.getenv("DEFAULT_SNACK_ID", "")


# =============================================================================
# HELPER — Cache sécurisé avec TTL (Audit Faille #1)
# =============================================================================

CACHE_TTL_SECONDS = 300  # 5 minutes — les tokens expirés sont purgés automatiquement

_config_cache: dict = {}       # { snack_id: config_dict }
_cache_timestamps: dict = {}   # { snack_id: float (epoch) }
_cache_lock = threading.Lock() # Thread-safe car _dispatch_choice tourne en thread


def _cache_get(snack_id: str) -> Optional[dict]:
    """Retourne la config cachée si elle n'a pas expiré, sinon None."""
    with _cache_lock:
        ts = _cache_timestamps.get(snack_id)
        if ts and (time.time() - ts) < CACHE_TTL_SECONDS:
            return _config_cache.get(snack_id)
        # Expirée ou absente → purge
        _config_cache.pop(snack_id, None)
        _cache_timestamps.pop(snack_id, None)
        return None


def _cache_set(snack_id: str, config: dict) -> None:
    """Stocke la config en cache avec un timestamp."""
    with _cache_lock:
        _config_cache[snack_id] = config
        _cache_timestamps[snack_id] = time.time()


# =============================================================================
# HELPER — Sanitisation des inputs (Skill_Safety_Gate §4)
# =============================================================================

def _sanitize(value: str, max_len: int = 255) -> str:
    """
    Retire les caractères dangereux et tronque.
    Protège contre les injections de scripts dans les payloads WhatsApp.
    """
    cleaned = re.sub(r'[<>"\';&+%]', "", str(value))
    return cleaned[:max_len].strip()


# =============================================================================
# HELPER — Redaction PII pour les logs (Skill_Safety_Gate §5)
# =============================================================================

def _redact(value: str, visible: int = 6) -> str:
    """Masque partiellement une valeur sensible pour les logs."""
    if not value or len(value) <= visible:
        return "***"
    return value[:visible] + "***"


# =============================================================================
# HELPER — Chargement config restaurant (avec cache TTL)
# =============================================================================

def _load_config(snack_id: str) -> Optional[dict]:
    """
    Charge la config du restaurant depuis le cache TTL ou depuis GSheets.
    Le cache expire après 5 minutes → les tokens mis à jour dans GSheets
    sont automatiquement récupérés sans redémarrage.
    Retourne None si snack_id inconnu.
    """
    cached = _cache_get(snack_id)
    if cached is not None:
        return cached
    try:
        config = get_snack_config(snack_id)
        _cache_set(snack_id, config)
        return config
    except KeyError as e:
        print(f"⚠️  {e}")
        return None


# =============================================================================
# ROUTE 1 : /webhook — Point d'entrée WhatsApp (message entrant)
# =============================================================================

# =============================================================================
# ROUTE 0 : /webhook GET — Vérification Meta (obligatoire pour l'enregistrement)
# =============================================================================

@app.route("/webhook", methods=["GET"])
def whatsapp_verify():
    """
    Endpoint de vérification Meta WhatsApp Business.
    Meta envoie une requête GET avec hub.mode, hub.verify_token et hub.challenge.
    On renvoie hub.challenge si le verify_token correspond à WHATSAPP_VERIFY_TOKEN.
    """
    mode      = request.args.get("hub.mode", "")
    token     = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")

    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    if mode == "subscribe" and token == verify_token:
        print(f"✅ Webhook vérifié par Meta — challenge={challenge}")
        return challenge, 200

    print(f"❌ Vérification échouée | token reçu='{token}' | attendu='{verify_token}'")
    return jsonify({"error": "Forbidden — token invalide"}), 403


# =============================================================================
# ROUTE 1 : /webhook POST — Point d'entrée WhatsApp (message entrant)
# =============================================================================

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    """
    Webhook Meta WhatsApp Business : reçoit les messages entrants.
    Payload JSON attendu :
      {
        "snack_id":       "SNACK_PARIS_01",
        "customer_phone": "+33785557054",
        "choice":         "1" | "2"         # 1=Menu, 2=Rappel
      }
    """
    data = request.get_json(force=True, silent=True) or {}

    snack_id       = _sanitize(data.get("snack_id",       DEFAULT_SNACK_ID), max_len=50)
    customer_phone = _sanitize(data.get("customer_phone", ""), max_len=20)
    choice         = _sanitize(data.get("choice",         ""), max_len=2)

    print(f"\n📲 Webhook | snack_id={snack_id} | client={_redact(customer_phone)} | choix={choice}")

    if not snack_id or not customer_phone:
        return jsonify({"error": "snack_id et customer_phone sont requis"}), 400

    # Normalisation E.164
    norm = safe_normalize(customer_phone)
    caller_e164 = norm if norm else customer_phone

    # Chargement config restaurant
    config = _load_config(snack_id)
    if not config:
        return jsonify({"error": f"snack_id '{snack_id}' introuvable"}), 404

    # Traitement asynchrone pour rester < 3 s
    threading.Thread(
        target=_dispatch_choice,
        args=(config, caller_e164, choice),
        daemon=True,
    ).start()

    return jsonify({"status": "accepted", "snack_id": snack_id}), 202


# =============================================================================
# DISPATCH — Orchestration asynchrone du choix
# =============================================================================

def _dispatch_choice(config: dict, caller_e164: str, choice: str):
    """
    Orchestre les actions selon le choix du client :
      1 → Menu interactif WhatsApp + ticket cuisine
      2 → Notification rappel au restaurant
    """
    snack_id = config.get("snack_id", "?")

    if choice == "1":
        _handle_option_1(config, caller_e164)
    elif choice == "2":
        _handle_option_2(config, caller_e164)
    else:
        print(f"⚠️  [{snack_id}] Choix invalide reçu : '{choice}' pour {_redact(caller_e164)}")
        log_order(
            snack_id=snack_id,
            customer_phone=caller_e164,
            order_details=f"Choix invalide : '{choice}'",
            status="Échec",
        )


# =============================================================================
# ORCHESTRATION — Fonctions asynchrones (Layer 2 Logic)
# =============================================================================

def _handle_option_1(config: dict, caller_e164: str):
    """
    Option 1 — Envoi du menu interactif WhatsApp au client :
    1. Vérifie la fidélité du client
    2. Envoie menu interactif (ou message fidélité si LOYAL)
    3. Envoie un ticket cuisine au restaurant
    4. Log dans COMMANDES
    5. Upsert CRM
    """
    snack_id = config.get("snack_id", "?")
    print(f"\n🚀 [OPTION 1] Démarrage | {_redact(caller_e164)} | {snack_id}")

    wa_status = "Échec"

    # Étape 1 : Fidélité
    try:
        loyalty = check_customer_loyalty(snack_id, caller_e164)
    except Exception as e:
        print(f"⚠️  Fidélité non vérifiable : {e}")
        loyalty = "NEW"

    # Étape 2 : Menu WhatsApp (adapté selon fidélité)
    try:
        if loyalty == "LOYAL":
            wa_result = send_loyalty_welcome(config, caller_e164)
        else:
            wa_result = send_interactive_menu(config, caller_e164)

        if "error" not in wa_result:
            wa_status = "Lien envoyé"
            print(f"✅ Menu WhatsApp envoyé à {_redact(caller_e164)} ({loyalty})")
        else:
            wa_status = f"Échec: {wa_result.get('error')}"
            print(f"❌ Échec envoi menu à {_redact(caller_e164)}")
    except Exception as e:
        wa_status = f"Erreur: {e}"
        print(f"❌ Erreur critique envoi menu : {e}")

    # Étape 3 : Ticket cuisine au restaurateur
    try:
        ticket_data = {
            "customer_phone": caller_e164,
            "items":  [{"name": "Commande en ligne", "quantity": 1}],
            "total":  "—",
            "notes":  f"Fidélité : {loyalty}",
        }
        send_kitchen_ticket(config, ticket_data)
    except Exception as e:
        print(f"⚠️  Ticket cuisine non envoyé : {e}")

    # Étape 4 : Log GSheets
    log_order(
        snack_id=snack_id,
        customer_phone=caller_e164,
        order_details=f"Option 1 — Menu | Fidélité: {loyalty}",
        status=wa_status,
    )

    # Étape 5 : CRM
    try:
        upsert_client(caller_e164, snack_id, ivr_choice="1")
        log_interaction(caller_e164, snack_id, "1 - Menu WhatsApp", wa_status, "N/A")
    except Exception as e:
        print(f"⚠️  CRM non disponible : {e}")

    print(f"✅ [OPTION 1] Terminé | {_redact(caller_e164)} | WA: {wa_status}\n")


def _handle_option_2(config: dict, caller_e164: str):
    """
    Option 2 — Rappel manuel : notifie le restaurant qu'un client attend.
    Log dans COMMANDES.
    """
    snack_id = config.get("snack_id", "?")
    print(f"\n🚀 [OPTION 2] Rappel demandé | {caller_e164} | {snack_id}")

    # Notification au restaurateur
    try:
        send_text_message(
            config,
            config.get("resto_phone", ""),
            f"📞 *Rappel demandé*\nClient : {caller_e164}\nMerci de le rappeler dès que possible.",
        )
    except Exception as e:
        print(f"⚠️  Notification rappel non envoyée : {e}")

    # Log GSheets
    log_order(
        snack_id=snack_id,
        customer_phone=caller_e164,
        order_details="Option 2 — Demande de rappel",
        status="En attente",
    )

    # CRM
    try:
        upsert_client(caller_e164, snack_id, ivr_choice="2")
        log_interaction(caller_e164, snack_id, "2 - Rappel", "N/A", "En attente")
    except Exception as e:
        print(f"⚠️  CRM non disponible : {e}")

    print(f"✅ [OPTION 2] Log enregistré | {caller_e164}\n")


# =============================================================================
# HEALTH CHECK — Route de vérification
# =============================================================================

@app.route("/health", methods=["GET"])
def health_check():
    """Endpoint de vérification que le serveur est actif."""
    return {"status": "ok", "service": "Snack-Flow IVR", "version": "1.0"}, 200


# =============================================================================
# INITIALISATION
# =============================================================================

if __name__ == "__main__":
    print("🚀 Snack-Flow — Webhook WhatsApp — Démarrage Layer 2")
    print("━" * 50)

    # Vérification complète des variables critiques (Skill_Safety_Gate ②)
    REQUIRED_VARS = [
        "GOOGLE_SHEET_ID",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_VERIFY_TOKEN",
        "DEFAULT_SNACK_ID",
    ]
    alerts = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if alerts:
        print(f"⚠️  Variables .env manquantes : {alerts}")
    else:
        print("✅ Toutes les variables critiques sont présentes")

    print("━" * 50)
    # Check for port
    port = int(os.getenv("SERVER_PORT", 5001))
    print(f"✅ Webhook prêt — En écoute sur http://0.0.0.0:{port}")
    print("   Routes disponibles :")
    print("   - POST /webhook → Message WhatsApp entrant (choix 1 ou 2)")
    print("   - GET  /health  → Health check")
    print("━" * 50)

    app.run(host="0.0.0.0", port=port, debug=False)
