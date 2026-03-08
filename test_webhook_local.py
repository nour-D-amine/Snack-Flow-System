import requests
import json
import time
import sys

def test_webhook():
    url = "http://localhost:5001/webhook"
    
    # Payload simulant un message WhatsApp entrant
    payload = {
        "snack_id": "SNACK_TEST_01", # On tentera un snack ID ou ça retombera sur le default
        "customer_phone": "+33785557054",
        "choice": "1"
    }
    
    print(f"🚀 Simulation d'envoi Webhook vers {url} ...")
    print(f"📦 Payload : {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        print(f"\n✅ Réponse du serveur ({response.status_code}) :")
        print(response.json())
        
        if response.status_code in [200, 202]:
            print("\n✅ Test réussi : Le Flask a bien accepté la requête.")
            sys.exit(0)
        else:
            print("\n❌ Test échoué : Le Flask a renvoyé une erreur.")
            sys.exit(1)
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Test échoué : Le serveur Flask n'est pas joignable. Est-il lancé ?")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erreur inattendue : {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Laisser un peu de temps au cas où le serveur viendrait d'être lancé
    time.sleep(2)
    test_webhook()
