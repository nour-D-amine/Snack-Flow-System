import os
import json
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

def generate_signature(payload_bytes, secret):
    return "sha256=" + hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

def test_e2e():
    url = "http://localhost:5001/webhook"
    
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "12345",
                "changes": [
                    {
                        "value": {
                            "metadata": {
                                "phone_number_id": "15557586424",
                                "display_phone_number": "15557586424"
                            },
                            "contacts": [
                                {
                                    "profile": {
                                        "name": "Test User"
                                    },
                                    "wa_id": "33785557054"
                                }
                            ],
                            "messages": [
                                {
                                    "from": "33785557054",
                                    "id": "wamid.HBgLMzMzMzMzMzMzMzM=",
                                    "timestamp": "1609459200",
                                    "text": {
                                        "body": "Je voudrais un Menu Burger Classic et un Tiramisu svp."
                                    },
                                    "type": "text"
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

    payload_bytes = json.dumps(payload).encode('utf-8')
    secret = os.getenv("WHATSAPP_APP_SECRET", "")
    headers = {"Content-Type": "application/json"}
    
    if secret:
        signature = generate_signature(payload_bytes, secret)
        headers["X-Hub-Signature-256"] = signature

    print("🚀 Début du test E2E : Simulation d'une commande cliente...")
    try:
        response = requests.post(url, data=payload_bytes, headers=headers)
        print("📨 Statut de la requête au Webhook:", response.status_code)
        print("📨 Réponse:", response.text)
        print("⏳ Le traitement se fait en arrière-plan. Vérifiez les logs du serveur (orchestrator) !")
    except requests.exceptions.ConnectionError:
        print("❌ Serveur injoignable. Le serveur local tourne-t-il sur le port 5001 ?")

if __name__ == "__main__":
    test_e2e()
