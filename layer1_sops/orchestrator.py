"""
Layer 1 — SOPs : Orchestrateur Principal (Snack-Flow v2.0 Full-WhatsApp)
=========================================================================
Point d'entrée du système Snack-Flow.

Responsabilités :
  - Vérification de l'environnement (.env)
  - Démarrage du serveur WhatsApp Webhook (Layer 2)
  - Surveillance et self-healing du processus
  - Arrêt propre sur signal SIGTERM/SIGINT

Architecture : Orchestrateur → WhatsApp Webhook (Layer 2) → Supabase + WA (Layer 3)

SUPPRIMÉ en v2.0 :
  - Twilio / IVR / SMS
  - Google Sheets
  - SQLite (crm_tool)
  - Notion
"""

import os
import sys
import subprocess
import time
import signal
import threading
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVER_PORT            = int(os.getenv("SERVER_PORT", "5001"))
SERVER_HOST            = os.getenv("SERVER_HOST", "0.0.0.0")
HEALTH_CHECK_INTERVAL  = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))  # secondes

_server_process = None
_shutdown_event = threading.Event()


# =============================================================================
# SOP-001 : VÉRIFICATION DE L'ENVIRONNEMENT
# =============================================================================

def sop_verify_environment() -> dict:
    """
    SOP-001 : Vérifie que toutes les variables critiques sont présentes
    avant de démarrer le système.

    :return: {"status": "ok"|"warning"|"error", "missing": [], "report": str}
    """
    print("\n🔍 [SOP-001] Vérification de l'environnement...")

    required_vars = {
        "SUPABASE_URL":               "URL du projet Supabase",
        "SUPABASE_SERVICE_ROLE_KEY":  "Clé service_role Supabase (côté serveur)",
        "WHATSAPP_PHONE_NUMBER_ID":   "ID du numéro WhatsApp Business (Meta)",
        "WHATSAPP_ACCESS_TOKEN":      "Token d'accès Meta Graph API",
        "WHATSAPP_VERIFY_TOKEN":      "Token de vérification webhook Meta",
        "WHATSAPP_APP_SECRET":        "App Secret Meta (signature HMAC des webhooks)",
    }

    # DEFAULT_SNACK_ID is optional (mono-tenant dev fallback only)
    optional_vars = {"DEFAULT_SNACK_ID", "MENU_URL", "GEMINI_API_KEY"}

    missing_critical = []
    missing_optional = []

    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            if var in optional_vars:
                missing_optional.append(f"  ⚠️  {var} — {description}")
            else:
                missing_critical.append(f"  ❌ {var} — {description}")

    report_lines = ["━" * 55, "📋 RAPPORT ENVIRONNEMENT — Snack-Flow v2.0", "━" * 55]

    if not missing_critical and not missing_optional:
        report_lines.append("✅ Toutes les variables sont configurées.")
        status = "ok"
    elif missing_critical:
        report_lines.append("❌ Variables CRITIQUES manquantes :")
        report_lines.extend(missing_critical)
        status = "error"
    else:
        report_lines.append("⚠️  Variables optionnelles manquantes :")
        report_lines.extend(missing_optional)
        status = "warning"

    report_lines.append("━" * 55)
    report = "\n".join(report_lines)
    print(report)

    return {
        "status":           status,
        "missing_critical": missing_critical,
        "missing_optional": missing_optional,
        "report":           report,
    }


# =============================================================================
# SOP-002 : DÉMARRAGE DU SERVEUR WHATSAPP WEBHOOK
# =============================================================================

def sop_start_webhook_server() -> bool:
    """
    SOP-002 : Démarre le serveur Flask WhatsApp Webhook (Layer 2)
    comme processus principal.
    """
    global _server_process

    webhook_script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "layer2_navigation",
        "whatsapp_webhook.py"
    )

    print(f"\n🚀 [SOP-002] Démarrage du serveur WhatsApp Webhook...")
    print(f"   Script : {webhook_script}")
    print(f"   Écoute : http://{SERVER_HOST}:{SERVER_PORT}")

    try:
        _server_process = subprocess.Popen(
            [sys.executable, webhook_script],
            env=os.environ.copy()
        )
        print(f"✅ Serveur WhatsApp Webhook démarré (PID: {_server_process.pid})")
        return True
    except Exception as e:
        print(f"❌ Impossible de démarrer le serveur : {e}")
        return False


# =============================================================================
# SOP-003 : HEALTH MONITOR — Surveillance et self-healing
# =============================================================================

def sop_health_monitor():
    """
    SOP-003 : Surveille le serveur Webhook et le redémarre si nécessaire.
    S'exécute dans un thread séparé. Self-Healing automatique.
    """
    global _server_process
    restart_count = 0
    max_restarts  = 3

    print(f"\n🩺 [SOP-003] Health monitor actif (interval: {HEALTH_CHECK_INTERVAL}s)")

    while not _shutdown_event.is_set():
        _shutdown_event.wait(HEALTH_CHECK_INTERVAL)

        if _shutdown_event.is_set():
            break

        if _server_process and _server_process.poll() is not None:
            exit_code = _server_process.returncode
            print(f"\n🚨 [SOP-003] Serveur arrêté (code: {exit_code}) — Redémarrage...")

            if restart_count < max_restarts:
                restart_count += 1
                print(f"   Tentative {restart_count}/{max_restarts}...")
                if sop_start_webhook_server():
                    print(f"✅ Serveur redémarré avec succès.")
                    restart_count = 0
                else:
                    print(f"❌ Redémarrage échoué.")
            else:
                print(f"❌ [SOP-003] {max_restarts} redémarrages max atteints. Arrêt du système.")
                _shutdown_event.set()
                break
        else:
            ts = datetime.now().strftime("%H:%M:%S")
            pid = _server_process.pid if _server_process else "N/A"
            print(f"💚 [{ts}] Webhook actif (PID: {pid})")


# =============================================================================
# SOP-004 : ARRÊT PROPRE
# =============================================================================

def sop_graceful_shutdown(signum=None, frame=None):
    """SOP-004 : Arrêt propre sur SIGTERM / SIGINT."""
    print("\n\n🛑 [SOP-004] Signal d'arrêt reçu — Arrêt propre...")
    _shutdown_event.set()

    if _server_process and _server_process.poll() is None:
        print(f"   Arrêt du serveur Webhook (PID: {_server_process.pid})...")
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
            print("✅ Serveur arrêté proprement.")
        except subprocess.TimeoutExpired:
            print("⚠️  Timeout — Forçage SIGKILL...")
            _server_process.kill()

    print("✅ Snack-Flow System — Arrêt complet. À bientôt !")
    sys.exit(0)


# =============================================================================
# POINT D'ENTRÉE PRINCIPAL
# =============================================================================

def main():
    print("\n" + "═" * 55)
    print("  🍔  SNACK-FLOW v2.0 — FULL-WHATSAPP — DÉMARRAGE")
    print(f"  📅  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 55)

    # SOP-001 : Vérification environnement
    env_result = sop_verify_environment()
    if env_result["status"] == "error":
        print("\n❌ Variables critiques manquantes — Complétez le fichier .env")
        sys.exit(1)

    # Gestion signaux
    signal.signal(signal.SIGTERM, sop_graceful_shutdown)
    signal.signal(signal.SIGINT,  sop_graceful_shutdown)

    # SOP-002 : Démarrage serveur Webhook
    if not sop_start_webhook_server():
        print("\n❌ Impossible de démarrer le serveur Webhook. Arrêt.")
        sys.exit(1)

    # SOP-003 : Health monitor en arrière-plan
    monitor_thread = threading.Thread(target=sop_health_monitor, daemon=True)
    monitor_thread.start()

    print("\n" + "═" * 55)
    print("✅ Snack-Flow v2.0 OPÉRATIONNEL")
    print(f"   Webhook URL : http://{SERVER_HOST}:{SERVER_PORT}/webhook")
    print(f"   Health Check: http://{SERVER_HOST}:{SERVER_PORT}/health")
    print("   Appuyez sur Ctrl+C pour arrêter.")
    print("═" * 55 + "\n")

    try:
        while not _shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        sop_graceful_shutdown()


if __name__ == "__main__":
    main()
