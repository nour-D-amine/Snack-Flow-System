"""
test_webhook_v2.py — Test End-to-End Snack-Flow v3.0
=====================================================
Adapté pour le schéma init.sql v3.0 :
  - snacks  : id (UUID), name, whatsapp_phone_number_id, is_active
  - orders  : id (UUID), snack_id (UUID FK), customer_phone, items (JSONB), status

Flow du test :
  1. Insère un snack de test (v3 schema) dans Supabase
  2. Démarre le serveur Flask (webhook)
  3. Envoie un payload Meta réel simulé (phone_number_id → auth tenant)
  4. Vérifie l'ordre créé dans Supabase
  5. Nettoie les données de test
"""

import os
import time
import requests
import subprocess
import json
import sys

from dotenv import load_dotenv

load_dotenv()

# ─── Constantes de test ────────────────────────────────────────────────────────

TEST_PHONE_NUMBER_ID = "FAKE_PHONE_ID_V3"
TEST_CUSTOMER_PHONE  = "+33612345678"
TEST_SNACK_NAME      = "Snack Test v3"


def _upsert_test_snack(sb) -> str:
    """
    Insère ou met à jour le snack de test (schéma v3).
    Retourne l'UUID du snack créé.
    """
    # Upsert : ON CONFLICT sur whatsapp_phone_number_id
    resp = (
        sb.table("snacks")
        .upsert(
            {
                "name":                     TEST_SNACK_NAME,
                "whatsapp_phone_number_id": TEST_PHONE_NUMBER_ID,
                "is_active":                True,
            },
            on_conflict="whatsapp_phone_number_id",
        )
        .execute()
    )
    if resp.data:
        snack_uuid = resp.data[0]["id"]
        print(f"✅ Snack v3 upsert → id={snack_uuid} | name='{TEST_SNACK_NAME}'")
        return snack_uuid

    # Fallback : SELECT si upsert ne retourne rien
    row = (
        sb.table("snacks")
        .select("id")
        .eq("whatsapp_phone_number_id", TEST_PHONE_NUMBER_ID)
        .single()
        .execute()
    )
    snack_uuid = row.data["id"]
    print(f"✅ Snack v3 récupéré → id={snack_uuid}")
    return snack_uuid


def _cleanup_test_data(sb, snack_uuid: str):
    """
    Supprime les données de test créées par ce run.
    """
    try:
        sb.table("orders").delete().eq("customer_phone", TEST_CUSTOMER_PHONE).execute()
        sb.table("snacks").delete().eq("id", snack_uuid).execute()
        print("🧹 Données de test supprimées.")
    except Exception as e:
        print(f"⚠️  Nettoyage partiel : {e}")


def run_test():
    # ── 0. Import du client Supabase ──────────────────────────────────────────
    from layer3_tools.supabase_tool import get_client
    sb = get_client()

    snack_uuid = None

    # ── 1. Création du snack de test (schéma v3) ──────────────────────────────
    print("\n🍔 [TEST] 1. Création du snack (schéma v3) dans Supabase...")
    try:
        snack_uuid = _upsert_test_snack(sb)
    except Exception as e:
        print(f"❌ Erreur création snack v3 : {e}")
        return

    # ── 2. Démarrage du serveur Flask ─────────────────────────────────────────
    print("\n🚀 [TEST] 2. Démarrage du serveur Flask (webhook)...")
    env = os.environ.copy()
    env["FLASK_ENV"] = "development"
    server_process = subprocess.Popen(
        [sys.executable, "layer2_navigation/whatsapp_webhook.py"],
        env=env
    )
    time.sleep(2)  # Laisse le serveur démarrer

    # ── 3. Envoi du payload Meta simulé ──────────────────────────────────────
    print(f"\n📲 [TEST] 3. Envoi d'un message WhatsApp simulé...")

    meta_payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "ENTRY_TEST_001",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "33600000000",
                        # phone_number_id → authentification tenant v3
                        "phone_number_id": TEST_PHONE_NUMBER_ID,
                    },
                    "contacts": [{
                        "profile": {"name": "Test User v3"},
                        "wa_id":   "33612345678",
                    }],
                    "messages": [{
                        "from":      "33612345678",
                        "id":        "wamid.FAKEID_V3_TEST",
                        "timestamp": "1720000000",
                        "type":      "text",
                        "text": {
                            "body": "Bonjour, je voudrais 2 burgers et 1 frite s'il vous plaît !"
                        }
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    port = os.getenv("SERVER_PORT", "5001")
    webhook_url = f"http://127.0.0.1:{port}/webhook"

    try:
        response = requests.post(webhook_url, json=meta_payload, timeout=10)
        print(f"✅ Webhook a répondu : HTTP {response.status_code} — {response.text}")
    except Exception as e:
        print(f"❌ Erreur requête HTTP : {e}")

    # Laisse le thread asynchrone terminer ses insertions
    time.sleep(5)

    # ── 4. Vérification dans Supabase (schéma v3) ────────────────────────────
    print("\n🔍 [TEST] 4. Vérification des données dans Supabase (v3)...\n")

    orders_ok = False
    try:
        # Commandes pour le client de test, filtrées par snack_id UUID
        orders = (
            sb.table("orders")
            .select("*")
            .eq("customer_phone", TEST_CUSTOMER_PHONE)
            .eq("snack_id", snack_uuid)
            .execute()
        )

        if orders.data:
            for i, order in enumerate(orders.data, 1):
                status = order.get("status", "N/A")
                items  = order.get("items", [])
                print(
                    f"   🍔 Commande #{i} | status=[{status}] "
                    f"| items={json.dumps(items, ensure_ascii=False)}"
                )
            orders_ok = True
            print(f"\n   ✅ table `orders` : {len(orders.data)} commande(s) trouvée(s).")
        else:
            print(f"   ❌ table `orders` : 0 commande trouvée pour snack_id={snack_uuid}")

    except Exception as e:
        print(f"❌ Erreur Supabase SELECT orders : {e}")

    # ── 5. Arrêt du serveur ───────────────────────────────────────────────────
    print("\n🛑 Arrêt du webhook...")
    server_process.terminate()
    server_process.wait()

    # ── 6. Nettoyage ─────────────────────────────────────────────────────────
    print("\n🧹 [TEST] 5. Nettoyage des données de test...")
    if snack_uuid:
        _cleanup_test_data(sb, snack_uuid)

    # ── Résultat final ────────────────────────────────────────────────────────
    if orders_ok:
        print("\n🏆 TEST RÉUSSI — Flow v3.0 (auth multi-tenant + Gemini parsing) opérationnel !")
    else:
        print("\n⚠️  TEST INCOMPLET — Vérifiez que init.sql v3 est appliqué sur Supabase.")
        print("   → Supabase Dashboard → SQL Editor → Coller et exécuter init.sql")


if __name__ == "__main__":
    run_test()
