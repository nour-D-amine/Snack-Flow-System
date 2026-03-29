"""
Layer 3 — Tools : Alert Tool (SnackFlow v2.1)
=============================================
Système d'alertes critiques via Telegram Bot API.

Utilisé par le décorateur @error_monitor sur les routes Flask critiques :
  - Envoie un message Telegram au gérant en cas d'erreur 500 ou d'échec IA.
  - Fallback vers le logger si Telegram n'est pas configuré.
  - Non-bloquant : l'envoi Telegram se fait dans un thread séparé pour
    ne pas ralentir la réponse Flask.

Variables .env requises :
  TELEGRAM_BOT_TOKEN   Token du bot Telegram (ex: 123456:ABCdef...)
                       Obtenu via @BotFather sur Telegram.
  TELEGRAM_CHAT_ID     Chat ID du destinataire (gérant / canal d'alertes).
                       Obtenez-le via @userinfobot ou en lisant l'API.

Variables .env optionnelles :
  ALERT_ENV_NAME       Nom de l'environnement affiché dans les alertes (défaut: "production").
"""

import logging
import os
import threading
import traceback
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Logger dédié ─────────────────────────────────────────────────────────────

logger = logging.getLogger("snack_flow.alert")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s | alert_tool | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ─── Configuration Telegram ───────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ALERT_ENV_NAME     = os.getenv("ALERT_ENV_NAME", "production").strip()

TELEGRAM_API_BASE  = "https://api.telegram.org"

# ─── Niveaux d'alerte ─────────────────────────────────────────────────────────

LEVEL_ICONS = {
    "critical": "🚨",
    "error":    "❌",
    "warning":  "⚠️",
    "info":     "ℹ️",
}


# =============================================================================
# ENVOI D'ALERTE TELEGRAM
# =============================================================================

def send_alert(
    title: str,
    body: str,
    level: str = "error",
    extra: Optional[dict] = None,
) -> bool:
    """
    Envoie une alerte sur le canal Telegram configuré.

    Si TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID sont absents,
    l'alerte est redirigée vers le logger (fallback non-bloquant).

    :param title: Titre court de l'alerte (affiché en gras).
    :param body:  Corps du message (détails, traceback tronqué, etc.).
    :param level: Niveau de sévérité : "critical" | "error" | "warning" | "info".
    :param extra: Dictionnaire optionnel de métadonnées additionnelles.
    :return: True si envoyé avec succès, False sinon.
    """
    icon     = LEVEL_ICONS.get(level, "🔔")
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    env_tag  = f"[{ALERT_ENV_NAME.upper()}]"

    # Construction du message HTML (plus simple à échapper que MarkdownV2)
    lines = [
        f"{icon} <b>{_html_escape(title)}</b>  {env_tag}",
        f"<code>{ts}</code>",
        "",
        _html_escape(body[:1800]),  # Telegram limite à ~4096 chars
    ]

    if extra:
        lines.append("")
        for k, v in extra.items():
            lines.append(f"• <b>{_html_escape(str(k))}</b>: {_html_escape(str(v)[:200])}")

    text = "\n".join(lines)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "⚠️  [alert_tool] Telegram non configuré (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manquants). "
            "Alerte redirigée vers le logger.\n%s\n%s", title, body[:400]
        )
        return False

    return _send_telegram_message(text)


def send_alert_async(
    title: str,
    body: str,
    level: str = "error",
    extra: Optional[dict] = None,
) -> None:
    """
    Version non-bloquante de send_alert (thread daemon).
    Utilisée par le décorateur @error_monitor pour ne pas bloquer la réponse Flask.
    """
    t = threading.Thread(
        target=send_alert,
        args=(title, body, level, extra),
        daemon=True,
        name="alert_sender",
    )
    t.start()


def notify_telegram(message: str) -> None:
    """
    Envoie un message Telegram simple au canal configuré (non-bloquant).
    Utilisé pour les notifications métier : nouvelle commande, push HubRise, etc.

    Contrairement à send_alert(), n'ajoute pas de formatage HTML alerte — envoie
    le texte brut tel quel. Non-bloquant (thread daemon).

    :param message: Texte du message (Markdown HTML supporté par Telegram).
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️  notify_telegram : TELEGRAM_BOT_TOKEN/CHAT_ID manquants — message ignoré.")
        return
    t = threading.Thread(
        target=_send_telegram_message,
        args=(message,),
        daemon=True,
        name="telegram_notify",
    )
    t.start()


# =============================================================================
# HELPERS INTERNES
# =============================================================================

def _send_telegram_message(text: str) -> bool:
    """Effectue l'appel HTTP vers l'API Telegram sendMessage."""
    endpoint = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload  = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=5)
        if response.status_code == 200:
            logger.info("✅ Alerte Telegram envoyée (chat_id=%s)", TELEGRAM_CHAT_ID)
            return True
        logger.error(
            "❌ Telegram API error : HTTP %s | %s",
            response.status_code, response.text[:200],
        )
        return False
    except requests.exceptions.Timeout:
        logger.error("⏱️  Timeout lors de l'envoi de l'alerte Telegram.")
        return False
    except Exception as exc:
        logger.error("💥 Erreur inattendue alert_tool : %s", exc)
        return False


def _html_escape(text: str) -> str:
    """Échappe les caractères spéciaux HTML pour l'API Telegram."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# =============================================================================
# UTILITAIRE — Résumé d'exception formaté
# =============================================================================

def format_exception_alert(exc: Exception, context: str = "") -> str:
    """
    Formate une exception en message d'alerte lisible.

    :param exc:     L'exception capturée.
    :param context: Contexte optionnel (nom de la route, fonction, etc.).
    :return: Texte formaté pour send_alert(body=...).
    """
    tb_lines = traceback.format_exc().splitlines()
    # On garde les 15 dernières lignes du traceback pour rester lisible
    tb_short = "\n".join(tb_lines[-15:]) if len(tb_lines) > 15 else "\n".join(tb_lines)

    parts = []
    if context:
        parts.append(f"Contexte : {context}")
    parts.append(f"Exception : {type(exc).__name__}: {exc}")
    parts.append("")
    parts.append("Traceback (extrait) :")
    parts.append(tb_short)

    return "\n".join(parts)


# =============================================================================
# TEST STANDALONE
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("   SnackFlow — Alert Tool — Self-Test")
    print("=" * 60)

    print("\n[1] Test alerte Telegram...")
    ok = send_alert(
        title="Test — Alert Tool SnackFlow",
        body="Ceci est un message de test. Si vous recevez ceci, Telegram est correctement configuré.",
        level="info",
        extra={"env": ALERT_ENV_NAME, "bot_token_set": bool(TELEGRAM_BOT_TOKEN)},
    )
    print(f"   → {'✅ Envoyé' if ok else '⚠️  Fallback logger (Telegram non configuré)'}")

    print("\n[2] Test format_exception_alert...")
    try:
        raise ValueError("Erreur de test simulée")
    except ValueError as e:
        msg = format_exception_alert(e, context="self_test")
        print("   →", msg[:200])

    print("\n" + "=" * 60)
    print("   ✅ Self-Test terminé")
    print("=" * 60)
