"""
Layer 3 — Tools : HubRise Connector (SnackFlow v2.0)
=====================================================
Pousse les commandes confirmées vers HubRise via l'API REST v1.

Flux :
  Gérant clique VALIDER
      │
      ▼
  push_to_hubrise(order, config)
      │
      ├─► POST https://api.hubrise.com/v1/locations/{location_id}/orders
      │         {status: "new", payment: cash, items: [...]}
      │
      └─► Retourne {"hubrise_order_id": "...", "status": "created"}

Documentation API HubRise :
  https://developers.hubrise.com/api/orders

Variables .env requises :
  HUBRISE_LOCATION_ID    ex: 1en7g-0
  HUBRISE_ACCESS_TOKEN   ex: eyJhb... (obtenu via OAuth2 HubRise)

Optionnel par tenant (colonnes table snacks, override .env) :
  hubrise_location_id
  hubrise_access_token

Variables .env OAuth2 (pour renouvellement auto du token) :
  HUBRISE_CLIENT_ID      477262765205.clients.hubrise.com
  HUBRISE_CLIENT_SECRET  d3f2f3d45bfc3624fe2b95bf4e2901b07f46be1183a378151e7284a3494cf397
  HUBRISE_REFRESH_TOKEN  (optionnel — si token direct non disponible)

Principes :
  - Zéro clé en dur — tout depuis .env ou config Supabase.
  - Self-Healing : si HubRise échoue → log "skipped" sans crasher le flux.
  - Paiement sur place : payment_type = "cash", status = "new".
  - Mapping Gemini → HubRise : name, qty, price avec defaults sûrs.
  - Multi-tenant : config Supabase prend la priorité sur les env vars.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# ─── Logger ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("snack_flow.hubrise")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s | hubrise_tool | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ─── Constantes ───────────────────────────────────────────────────────────────

HUBRISE_API_BASE  = "https://api.hubrise.com/v1"
HUBRISE_TOKEN_URL = "https://manager.hubrise.com/oauth2/v1/token"

# ─── Cache token en mémoire (thread-safe) ────────────────────────────────────

_token_cache: dict = {"access_token": "", "expires_at": 0.0}
_token_lock         = threading.Lock()


# =============================================================================
# HELPERS INTERNES — Credentials
# =============================================================================

def _get_access_token(config: Optional[dict] = None) -> str:
    """
    Résout l'access_token HubRise.

    Priorité :
      1. config["hubrise_access_token"] (override tenant Supabase)
      2. HUBRISE_ACCESS_TOKEN dans .env (token direct)
      3. Refresh via HUBRISE_REFRESH_TOKEN + CLIENT_ID + CLIENT_SECRET

    :raises ValueError: Si aucun token utilisable n'est disponible.
    """
    # Priorité 1 : override tenant (colonne snacks Supabase)
    if config:
        tenant_token = str(config.get("hubrise_access_token", "")).strip()
        if tenant_token:
            return tenant_token

    # Priorité 2 : token statique .env
    static_token = os.getenv("HUBRISE_ACCESS_TOKEN", "").strip()
    if static_token:
        return static_token

    # Priorité 3 : refresh token OAuth2
    refresh_token = os.getenv("HUBRISE_REFRESH_TOKEN", "").strip()
    client_id     = os.getenv("HUBRISE_CLIENT_ID", "477262765205.clients.hubrise.com").strip()
    client_secret = os.getenv("HUBRISE_CLIENT_SECRET", "").strip()

    if not (refresh_token and client_id and client_secret):
        raise ValueError(
            "Aucun token HubRise disponible. "
            "Configurez HUBRISE_ACCESS_TOKEN dans .env ou obtenez-en un via "
            "https://manager.hubrise.com puis ajoutez-le dans .env."
        )

    with _token_lock:
        # Réutilise le cache si encore valide
        if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
            return _token_cache["access_token"]

        logger.info("🔑 Renouvellement du token HubRise via refresh_token…")
        try:
            response = requests.post(
                HUBRISE_TOKEN_URL,
                data={
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type":    "refresh_token",
                },
                timeout=10,
            )
            data = response.json()
            if response.status_code not in (200, 201) or "access_token" not in data:
                raise ValueError(
                    f"HubRise refresh échoué : HTTP {response.status_code} | {data}"
                )
            _token_cache["access_token"] = data["access_token"]
            _token_cache["expires_at"]   = time.time() + data.get("expires_in", 3600)
            logger.info("✅ Token HubRise renouvelé (expire dans %ds).", data.get("expires_in", 3600))
            return _token_cache["access_token"]
        except Exception as e:
            raise ValueError(f"Renouvellement token HubRise échoué : {e}") from e


def _get_location_id(config: Optional[dict] = None) -> str:
    """
    Résout le HUBRISE_LOCATION_ID.

    Priorité :
      1. config["hubrise_location_id"] (override tenant Supabase)
      2. HUBRISE_LOCATION_ID dans .env

    :raises ValueError: Si absent partout.
    """
    if config:
        tenant_loc = str(config.get("hubrise_location_id", "")).strip()
        if tenant_loc:
            return tenant_loc

    location_id = os.getenv("HUBRISE_LOCATION_ID", "").strip()
    if not location_id:
        raise ValueError(
            "HUBRISE_LOCATION_ID absent. Ajoutez-le dans .env ou dans la colonne "
            "'hubrise_location_id' de la table snacks."
        )
    return location_id


# =============================================================================
# HELPERS INTERNES — Mapping
# =============================================================================

def _map_items(items: list) -> list:
    """
    Convertit les articles Gemini/Supabase vers le format HubRise v1.

    Format entrée (Gemini/Supabase) :
        [{"name": "Burger", "qty": 2, "price": 8.5}, ...]

    Format sortie HubRise :
        [{"product_name": "Burger", "quantity": "2",
          "price": "8.50 EUR", "subtotal": "17.00 EUR"}, ...]

    Note : HubRise accepte price/subtotal en string "X.XX EUR"
           ou en centimes entiers selon la version. On utilise le format string.
    """
    result = []
    for item in items:
        name  = str(item.get("name", "Article")).strip()
        qty   = int(item.get("qty", item.get("quantity", 1)))
        price = float(item.get("price") or 0.0)
        subtotal = round(price * qty, 2)

        entry = {
            "product_name": name,
            "quantity":     str(qty),
            "price":        f"{price:.2f} EUR",
            "subtotal":     f"{subtotal:.2f} EUR",
        }

        # Options (si présentes — format Gemini étendu)
        options = item.get("options", [])
        if options:
            entry["options"] = [{"name": str(opt)} for opt in options]

        result.append(entry)
    return result


def _build_payload(order: dict) -> dict:
    """
    Construit le payload JSON pour POST /locations/{id}/orders.

    Règles métier SnackFlow :
      - status       = "new"        (commande reçue, en attente caisse)
      - service_type = "collection" (retrait en restaurant, paiement sur place)
      - payment.type = "cash"       (paiement sur place)
    """
    items       = order.get("items", [])
    hub_items   = _map_items(items)
    customer_ph = str(order.get("customer_phone", "")).strip()

    # Calcul du total en EUR
    total_eur = sum(
        float(it["price"].replace(" EUR", "")) * int(it["quantity"])
        for it in hub_items
    )

    return {
        "status":       "new",
        "service_type": "collection",
        "channel":      "whatsapp",
        "private_ref":  str(order.get("id", "")),
        "customer_notes": f"Commande WhatsApp SnackFlow | {customer_ph}",
        "customer": {
            "phone": customer_ph,
        },
        "items": hub_items,
        "payment": {
            "type":   "cash",
            "amount": f"{total_eur:.2f} EUR",
        },
    }


# =============================================================================
# API PUBLIQUE
# =============================================================================

def push_to_hubrise(order: dict, config: Optional[dict] = None) -> dict:
    """
    Pousse une commande confirmée vers HubRise POS.

    Appelé par _handle_manager_callback() quand le gérant clique ✅ VALIDER.

    :param order:  Dict commande Supabase (id, customer_phone, items, status).
    :param config: Dict config snack issu de supabase_tool.get_snack_config()
                   (optionnel — utilisé pour override multi-tenant location/token).
    :return: {
                 "status":           "created" | "skipped" | "error",
                 "hubrise_order_id": str (si créé),
                 "message":          str (si erreur/skip),
             }
    """
    # ── Résolution credentials ────────────────────────────────────────────────
    try:
        access_token = _get_access_token(config)
        location_id  = _get_location_id(config)
    except ValueError as e:
        logger.warning("⚠️  [HubRise] Credentials absents — push ignoré : %s", e)
        return {"status": "skipped", "message": str(e)}

    # ── Construction du payload ───────────────────────────────────────────────
    try:
        payload = _build_payload(order)
    except Exception as e:
        logger.error("❌ [HubRise] Erreur construction payload : %s", e)
        return {"status": "error", "message": f"Payload error: {e}"}

    # ── Appel API HubRise ─────────────────────────────────────────────────────
    endpoint = f"{HUBRISE_API_BASE}/locations/{location_id}/orders"
    headers  = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }

    snack_name = config.get("name", "?") if config else "?"
    logger.info(
        "🚀 [HubRise] Envoi → location=%s | snack=%s | items=%d",
        location_id, snack_name, len(payload.get("items", [])),
    )

    try:
        response = requests.post(
            endpoint, headers=headers, json=payload, timeout=10,
        )
        data = response.json()

        if response.status_code in (200, 201):
            hubrise_id = data.get("id", "?")
            logger.info(
                "✅ [HubRise] Commande créée | hubrise_id=%s | order_ref=%s",
                hubrise_id, order.get("id", "?"),
            )
            return {
                "status":           "created",
                "hubrise_order_id": hubrise_id,
                "hubrise_status":   data.get("status"),
            }

        err_msg = data.get("message") or data.get("error") or str(data)
        logger.error("❌ [HubRise] Échec API | HTTP %s | %s", response.status_code, err_msg)
        return {"status": "error", "message": f"HTTP {response.status_code}: {err_msg}"}

    except requests.exceptions.Timeout:
        logger.error("⏱️  [HubRise] Timeout — commande non transmise.")
        return {"status": "error", "message": "timeout"}
    except Exception as exc:
        logger.error("💥 [HubRise] Erreur inattendue : %s", exc)
        return {"status": "error", "message": str(exc)}


def get_hubrise_order(hubrise_order_id: str, config: Optional[dict] = None) -> dict:
    """
    Récupère le détail d'une commande HubRise par son ID HubRise.

    :param hubrise_order_id: ID HubRise (ex: "a3b4c5").
    :param config:           Dict config snack (optionnel).
    :return: Dict HubRise ou {"error": ...}.
    """
    try:
        access_token = _get_access_token(config)
        location_id  = _get_location_id(config)
    except ValueError as e:
        return {"error": str(e)}

    endpoint = f"{HUBRISE_API_BASE}/locations/{location_id}/orders/{hubrise_order_id}"
    try:
        r = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=8,
        )
        return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}
    except Exception as exc:
        return {"error": str(exc)}


# =============================================================================
# TEST STANDALONE
# =============================================================================

if __name__ == "__main__":
    import json as _json

    print("=" * 60)
    print("   SnackFlow — HubRise Tool v2.0 — Self-Test")
    print(f"   Location : {os.getenv('HUBRISE_LOCATION_ID', 'NON CONFIGURÉ')}")
    print("=" * 60)

    MOCK_ORDER = {
        "id":             "order-uuid-test-001",
        "customer_phone": "+33785557054",
        "status":         "confirmed",
        "items": [
            {"name": "Burger Montagnard",  "qty": 2, "price": 8.50},
            {"name": "Frites Maison",      "qty": 1, "price": 3.00},
            {"name": "Coca-Cola 33cl",     "qty": 2, "price": 2.50},
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    MOCK_CONFIG = {
        "id":   "uuid-snack-prod",
        "name": "Le Snack du Coin",
        # Optionnel : override pour ce tenant
        # "hubrise_location_id":  "1en7g-0",
        # "hubrise_access_token": "votre-token",
    }

    print("\n[1] Test push_to_hubrise...")
    result = push_to_hubrise(MOCK_ORDER, MOCK_CONFIG)
    print("   →", _json.dumps(result, indent=4, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("   ✅ Self-Test terminé")
    print("=" * 60)
