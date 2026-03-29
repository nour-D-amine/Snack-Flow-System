"""Test direct du token WhatsApp avec envoi réel vers +33785557054."""
import os
from dotenv import load_dotenv
load_dotenv()

from layer3_tools.whatsapp_tool import send_text_message
from layer3_tools.supabase_tool import get_client, TABLE_SNACKS

# Récupère la config du snack K-REVIEW
client = get_client()
res = client.table(TABLE_SNACKS).select("*").eq("name", "K-REVIEW").single().execute()
config = res.data

PHONE = "+33785557054"
MSG = "✅ Test SnackFlow — Ton token permanent est validé ! Le système est opérationnel."

# Override du phone_number_id avec le vrai ID du .env
config["whatsapp_phone_number_id"] = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "919410367932677")

print(f"📤 Envoi d'un message de test vers {PHONE}...")
result = send_text_message(config=config, customer_phone=PHONE, body=MSG)
print("📨 Résultat :", result)
