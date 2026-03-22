#!/usr/bin/env python3
"""
Test E2E : 5 requêtes webhook simulant des payloads Meta WhatsApp.
Calcule la signature HMAC-SHA256 pour chaque requête, envoie via HTTP,
puis interroge Supabase pour vérifier les commandes.
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
import urllib.error

from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
WEBHOOK_URL     = "http://localhost:5001/webhook"
APP_SECRET      = os.getenv("WHATSAPP_APP_SECRET", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY    = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# 5 messages variés — numéro réel whitelisté Meta (sandbox)
TEST_CASES = [
    ("33785557054", "Un menu tacos poulet avec un coca"),
    ("33785557054", "Deux burgers classiques et une frite"),
    ("33785557054", "Je voudrais juste un café"),
    ("33785557054", "Un wrap veggie"),
    ("33785557054", "3 pizzas margherita"),
]

DIVIDER = "─" * 65


def build_meta_payload(from_phone: str, message: str) -> dict:
    """Construit un payload Meta WhatsApp Cloud API réaliste."""
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "ENTRY_TEST_001",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "15550000000",
                        "phone_number_id": PHONE_NUMBER_ID,
                    },
                    "messages": [{
                        "from":      from_phone,
                        "id":        f"wamid.test_{from_phone}_{int(time.time())}",
                        "timestamp": str(int(time.time())),
                        "type":      "text",
                        "text":      {"body": message},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


def sign_payload(body_bytes: bytes, secret: str) -> str:
    """Calcule X-Hub-Signature-256 = sha256=<HMAC(secret, body)>."""
    digest = hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def post_webhook(payload: dict, secret: str) -> tuple[int, dict]:
    """Envoie un POST JSON signé sur /webhook. Retourne (status_code, json_body)."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sig  = sign_payload(body, secret)

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type":        "application/json",
            "X-Hub-Signature-256": sig,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except Exception as exc:
        return 0, {"error": str(exc)}


def query_recent_orders(limit: int = 10) -> list:
    """Interroge Supabase REST directement pour les dernières commandes."""
    url = (
        f"{SUPABASE_URL}/rest/v1/orders"
        f"?select=id,snack_id,customer_phone,items,status,created_at"
        f"&order=created_at.desc"
        f"&limit={limit}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        return [{"error": str(exc)}]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'━'*65}")
    print("  Snack-Flow — Test E2E Webhook (5 requêtes Meta simulées)")
    print(f"{'━'*65}")
    print(f"  Webhook    : {WEBHOOK_URL}")
    print(f"  phone_id   : {PHONE_NUMBER_ID}")
    print(f"  secret     : {APP_SECRET[:8]}***")
    print(f"  Supabase   : {SUPABASE_URL[:40]}...")
    print(f"{'━'*65}\n")

    sent_phones = []

    # ── Phase 1 : Envoi des 5 requêtes ───────────────────────────────────────
    print("Phase 1 — Envoi des 5 requêtes webhook")
    print(DIVIDER)

    for i, (phone, msg) in enumerate(TEST_CASES, 1):
        payload = build_meta_payload(phone, msg)
        body    = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        sig     = sign_payload(body, APP_SECRET)

        print(f"\n[{i}/5] Message : \"{msg}\"")
        print(f"      Phone   : +{phone}")
        print(f"      HMAC    : {sig[:30]}...")

        status, resp_body = post_webhook(payload, APP_SECRET)
        icon = "✅" if status in (200, 202) else "❌"
        print(f"      Réponse : {icon} HTTP {status} → {resp_body}")

        if status in (200, 202):
            sent_phones.append(f"+{phone}")

        time.sleep(0.3)   # légère pause pour ne pas saturer le threadpool

    print(f"\n{DIVIDER}")
    print(f"  {len(sent_phones)}/5 requêtes acceptées par le webhook")

    # ── Phase 2 : Attente traitement asynchrone ───────────────────────────────
    print("\nPhase 2 — Attente du traitement asynchrone (6 s)…")
    for remaining in range(6, 0, -1):
        print(f"  ⏳ {remaining}s…", end="\r", flush=True)
        time.sleep(1)
    print("  ✅ Attente terminée            ")

    # ── Phase 3 : Vérification Supabase ──────────────────────────────────────
    print("\nPhase 3 — Vérification dans Supabase (table orders)")
    print(DIVIDER)

    orders = query_recent_orders(limit=10)

    if orders and "error" in orders[0]:
        print(f"\n  ❌ Supabase inaccessible : {orders[0]['error']}")
        print(f"\n{'━'*65}")
        print("  DIAGNOSTIC")
        print(f"{'━'*65}")
        print("  Le projet Supabase mvjpvygxqxtuauvzneex.supabase.co")
        print("  ne résout pas en DNS (NXDOMAIN).")
        print()
        print("  Causes possibles :")
        print("  1. Le projet Supabase n'a pas encore été créé")
        print("  2. Le projet est suspendu (free tier → inactif)")
        print("  3. La SUPABASE_URL dans .env est incorrecte")
        print()
        print("  Pour corriger :")
        print("  → Ouvrez https://supabase.com/dashboard")
        print("  → Vérifiez que le projet 'mvjpvygxqxtuauvzneex' existe")
        print("  → Si non : créez-le, récupérez la vraie URL + clé,")
        print("    puis mettez à jour .env et relancez le serveur.")
        print(f"{'━'*65}\n")
        sys.exit(1)

    # Filtrer uniquement les commandes envoyées dans ce test
    test_orders = [
        o for o in orders
        if o.get("customer_phone") in sent_phones
    ]

    confirmed = [o for o in test_orders if o.get("status") == "confirmed"]
    pending   = [o for o in test_orders if o.get("status") == "pending"]
    failed    = [o for o in test_orders if o.get("status") == "failed"]

    print(f"\n  Commandes trouvées pour ce test : {len(test_orders)}/5")
    print(f"  ✅ confirmed : {len(confirmed)}")
    print(f"  🕐 pending   : {len(pending)}")
    print(f"  ❌ failed    : {len(failed)}")
    print()

    for o in test_orders:
        status_icon = {"confirmed": "✅", "pending": "🕐", "failed": "❌"}.get(o.get("status", ""), "?")
        items_str   = json.dumps(o.get("items", []), ensure_ascii=False)
        print(f"  {status_icon} id={str(o.get('id',''))[:8]}…"
              f" | phone={o.get('customer_phone','')}"
              f" | status={o.get('status','')}"
              f" | items={items_str[:80]}")

    print(f"\n{'━'*65}")
    if len(confirmed) == 5:
        print("  🎉 TEST PASSÉ — 5/5 commandes 'confirmed' avec items parsés")
    elif len(test_orders) == 5:
        print(f"  ⚠️  TEST PARTIEL — {len(confirmed)}/5 confirmed | {len(failed)} failed")
    else:
        print(f"  ❌ TEST ÉCHOUÉ — seulement {len(test_orders)}/5 commandes en base")
    print(f"{'━'*65}\n")


if __name__ == "__main__":
    main()
