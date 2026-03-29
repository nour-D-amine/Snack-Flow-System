import os
from layer3_tools.alert_tool import send_alert

def send_telegram_alert(message):
    return send_alert(title="Test Message", body=message, level="info")

def test():
    print("🚀 Envoi de l'alerte de test...")
    success = send_telegram_alert("✅ SnackFlow est en ligne ! Le bot Telegram est opérationnel pour Luffy Boy.")
    if success:
        print("📱 C'est gagné ! Vérifie ton Telegram.")
    else:
        print("❌ Échec. Vérifie tes variables d'environnement sur Railway.")

if __name__ == "__main__":
    test()
