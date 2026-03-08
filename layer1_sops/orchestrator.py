"""
Layer 1 — SOPs : Orchestrateur Principal (Snack-Flow)
======================================================
Ce module est le POINT D'ENTRÉE du système Snack-Flow.
Il gère :
  - Le démarrage du serveur IVR (Layer 2)
  - Les procédures opérationnelles standards (SOPs)
  - La surveillance et le self-healing du système
  - Les rapports journaliers

Architecture : SOP Manager → IVR Server (Layer 2) → Tools (Layer 3)

Behavioral Rules :
  - Self-Healing : surveille le serveur et redémarre si nécessaire
  - Data-First : génère un rapport depuis Google Sheets avant l'arrêt
  - Determinism : comportement identique à chaque démarrage
"""

import os
import sys
import subprocess
import time
import signal
import threading
from datetime import datetime
from dotenv import load_dotenv

# --- Import des Tools Layer 3 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from layer3_tools.gsheets_tool import initialize_master_structures
from layer3_tools.phone_tool import normalize_e164

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

SERVER_PORT = int(os.getenv("SERVER_PORT", "5001"))
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))  # secondes

_server_process = None
_shutdown_event = threading.Event()


# =============================================================================
# SOP 1 : DÉMARRAGE — Vérification de l'environnement
# =============================================================================

def sop_verify_environment() -> dict:
    """
    SOP-001 : Vérifie que toutes les variables d'environnement critiques
    sont présentes avant de démarrer le système.

    :return: Dictionnaire {"status": "ok"|"warning"|"error", "missing": [], "report": str}
    """
    print("\n🔍 [SOP-001] Vérification de l'environnement...")

    required_vars = {
        "WHATSAPP_PHONE_NUMBER_ID": "ID du numéro WhatsApp Business (Meta)",
        "WHATSAPP_ACCESS_TOKEN":    "Token d'accès Meta Graph API",
        "GOOGLE_SHEET_ID":         "ID du Google Sheet Master (RESTOS + COMMANDES)",
        "MENU_URL":                "URL du menu interactif (fallback mono-restaurant)",
    }

    missing_critical = []
    missing_optional = []

    optional_vars = {"MENU_URL"}

    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            if var in optional_vars:
                missing_optional.append(f"  ⚠️  {var} — {description}")
            else:
                missing_critical.append(f"  ❌ {var} — {description}")

    # Rapport
    report_lines = ["━" * 50, "📋 RAPPORT ENVIRONNEMENT — Snack-Flow", "━" * 50]

    if not missing_critical and not missing_optional:
        report_lines.append("✅ Toutes les variables sont configurées.")
        status = "ok"
    elif missing_critical:
        report_lines.append("❌ Variables CRITIQUES manquantes (le système ne peut pas démarrer) :")
        report_lines.extend(missing_critical)
        status = "error"
    else:
        report_lines.append("⚠️  Variables optionnelles manquantes (fonctionnement dégradé) :")
        report_lines.extend(missing_optional)
        status = "warning"

    if missing_optional and status != "error":
        report_lines.append("\n⚠️  Variables optionnelles manquantes :")
        report_lines.extend(missing_optional)

    report_lines.append("━" * 50)
    report = "\n".join(report_lines)
    print(report)

    return {
        "status": status,
        "missing_critical": missing_critical,
        "missing_optional": missing_optional,
        "report": report
    }


# =============================================================================
# SOP 2 : INITIALISATION — Google Sheets
# =============================================================================

def sop_initialize_datastore() -> bool:
    """
    SOP-002 : Initialise les onglets RESTOS et COMMANDES du Google Sheet Master.
    Self-Healing : si échec, log l'erreur mais ne bloque pas le démarrage.

    :return: True si succès, False si échec (non bloquant).
    """
    print("\n📊 [SOP-002] Initialisation du datastore (Google Sheets Master)...")
    try:
        initialize_master_structures()
        print("✅ Google Sheets Master prêt (RESTOS + COMMANDES).")
        return True
    except Exception as e:
        print(f"⚠️  Google Sheets indisponible : {e}")
        print("   Le système démarrera quand même. Les logs seront en attente.")
        return False


# =============================================================================
# SOP 3 : DÉMARRAGE SERVEUR IVR
# =============================================================================

def sop_start_ivr_server():
    """
    SOP-003 : Démarre le serveur Flask IVR (Layer 2) comme processus principal.
    Cette fonction bloque jusqu'à l'arrêt du serveur.
    """
    global _server_process

    ivr_script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "layer2_navigation",
        "ivr_flow.py"
    )

    print(f"\n🚀 [SOP-003] Démarrage du serveur IVR Flask...")
    print(f"   Script : {ivr_script}")
    print(f"   Écoute : http://{SERVER_HOST}:{SERVER_PORT}")

    try:
        # Démarre le serveur IVR en subprocess pour pouvoir le surveiller
        _server_process = subprocess.Popen(
            [sys.executable, ivr_script],
            env=os.environ.copy()
        )
        print(f"✅ Serveur IVR démarré (PID: {_server_process.pid})")
        return True
    except Exception as e:
        print(f"❌ Impossible de démarrer le serveur IVR : {e}")
        return False


# =============================================================================
# SOP 4 : SURVEILLANCE — Health Check en arrière-plan
# =============================================================================

def sop_health_monitor():
    """
    SOP-004 : Surveille le serveur IVR et le redémarre si nécessaire.
    S'exécute dans un thread séparé.
    Self-Healing automatique.
    """
    global _server_process
    restart_count = 0
    max_restarts = 3

    print(f"\n🩺 [SOP-004] Health monitor actif (interval: {HEALTH_CHECK_INTERVAL}s)")

    while not _shutdown_event.is_set():
        _shutdown_event.wait(HEALTH_CHECK_INTERVAL)

        if _shutdown_event.is_set():
            break

        if _server_process and _server_process.poll() is not None:
            # Le serveur s'est arrêté inopinément
            exit_code = _server_process.returncode
            print(f"\n🚨 [SOP-004] Serveur IVR arrêté (code: {exit_code}) — Tentative de redémarrage...")

            if restart_count < max_restarts:
                restart_count += 1
                print(f"   Redémarrage {restart_count}/{max_restarts}...")
                if sop_start_ivr_server():
                    print(f"✅ Serveur IVR redémarré avec succès.")
                    restart_count = 0  # Reset si redémarrage réussi
                else:
                    print(f"❌ Redémarrage échoué.")
            else:
                print(f"❌ [SOP-004] Nb max de redémarrages atteint ({max_restarts}). Arrêt du système.")
                _shutdown_event.set()
                break
        else:
            # Serveur actif — log discret
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"💚 [{timestamp}] Serveur IVR actif (PID: {_server_process.pid if _server_process else 'N/A'})")


# =============================================================================
# SOP 5 : ARRÊT PROPRE — Shutdown gracieux
# =============================================================================

def sop_graceful_shutdown(signum=None, frame=None):
    """
    SOP-005 : Arrêt propre du système lors d'un signal SIGTERM/SIGINT.
    """
    print("\n\n🛑 [SOP-005] Signal d'arrêt reçu — Arrêt propre du système...")
    _shutdown_event.set()

    if _server_process and _server_process.poll() is None:
        print(f"   Arrêt du serveur IVR (PID: {_server_process.pid})...")
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
            print("✅ Serveur IVR arrêté proprement.")
        except subprocess.TimeoutExpired:
            print("⚠️  Timeout — Forçage de l'arrêt (SIGKILL)...")
            _server_process.kill()

    print("✅ Snack-Flow System — Arrêt complet. À bientôt !")
    sys.exit(0)


# =============================================================================
# POINT D'ENTRÉE PRINCIPAL
# =============================================================================

def main():
    """
    Fonction principale : exécute les SOPs dans l'ordre et démarre le système.
    """
    print("\n" + "═" * 60)
    print("  🍔  SNACK-FLOW SYSTEM — DÉMARRAGE")
    print(f"  📅  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 60)

    # --- SOP-001 : Vérification environnement ---
    env_result = sop_verify_environment()
    if env_result["status"] == "error":
        print("\n❌ Arrêt du système : variables critiques manquantes.")
        print("   Complétez le fichier .env et relancez.")
        sys.exit(1)

    # --- SOP-002 : Initialisation datastore ---
    sop_initialize_datastore()

    # --- Gestion signaux (arrêt propre) ---
    signal.signal(signal.SIGTERM, sop_graceful_shutdown)
    signal.signal(signal.SIGINT, sop_graceful_shutdown)

    # --- SOP-003 : Démarrage serveur IVR ---
    if not sop_start_ivr_server():
        print("\n❌ Impossible de démarrer le serveur IVR. Arrêt.")
        sys.exit(1)

    # --- SOP-004 : Health monitor en arrière-plan ---
    monitor_thread = threading.Thread(target=sop_health_monitor, daemon=True)
    monitor_thread.start()

    print("\n" + "═" * 60)
    print("✅ Snack-Flow System OPÉRATIONNEL")
    print(f"   IVR Webhook URL : http://{SERVER_HOST}:{SERVER_PORT}/webhook")
    print(f"   Health Check    : http://{SERVER_HOST}:{SERVER_PORT}/health")
    print("   Appuyez sur Ctrl+C pour arrêter le système.")
    print("═" * 60 + "\n")

    # --- Boucle principale : attente d'un signal d'arrêt ---
    try:
        while not _shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        sop_graceful_shutdown()


if __name__ == "__main__":
    main()
