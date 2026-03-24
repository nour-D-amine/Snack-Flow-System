"""
Layer 3 — Tools : HubRise Connector (SnackFlow v2.0)
=====================================================
Pousse les commandes confirmées vers HubRise via l'API REST v1.

Flux :
  Gérant clique VALIDER
      │
      ▼
  push_to_hubrise(order, access_token, location_id)
      │
      ├─► POST https://api.hubrise.com/v1/locations/{location_id}/orders
      │         {status: "new", payment: cash, items: [...]}
      │
      └─► Retourne {"hubrise_order_id": "...", "status": "created"}

Documentation API HubRise :
  https://developers.hubrise.com/api/orders

Architecture v2 — Credentials dynamiques :
  - access_token et location_id sont passés en paramètres (récupérés depuis Supabase).
  - Zéro variable d'environnement HubRise dans .env.
  - Chaque tenant a ses propres credentials dans la table snacks.

Principes :
  - Zéro clé en dur — tout depuis la base Supabase (colonnes snacks).
  - Self-Healing : si HubRise échoue → log "skipped" sans crasher le flux.
  - Paiement sur place : payment_type = "cash", status = "new".
  - Mapping Gemini → HubRise : name, qty, price avec defaults sûrs.
"""

import logging
from typing import Optional

import requests

# ─── Logger ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("snack_flow.hubrise")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s | hubrise_tool | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ─── Constante ────────────────────────────────────────────────────────────────

HUBRISE_API_BASE = "https://api.hubrise.com/v1"


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
    """
    result = []
    for item in items:
        name = str(item.get("name", "Article")).strip()
        qty = int(item.get("qty", item.get("quantity", 1)))
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
      - payment.type = "cash"       (paiement sur place — mode 'unpaid')
    """
    items = order.get("items", [])
    hub_items = _map_items(items)
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

def push_to_hubrise(
    order: dict,
    access_token: str,
    location_id: str,
    snack_name: str = "?",
) -> dict:
    """
    Pousse une commande confirmée vers HubRise POS.

    Appelé par _handle_manager_callback() quand le gérant clique ✅ VALIDER.

    :param order:        Dict commande Supabase (id, customer_phone, items, status).
    :param access_token: Token OAuth2 HubRise pour ce tenant (depuis snacks table).
    :param location_id:  Location ID HubRise pour ce tenant (depuis snacks table).
    :param snack_name:   Nom du snack (pour les logs).
    :return: {
                 "status":           "created" | "skipped" | "error",
                 "hubrise_order_id": str (si créé),
                 "message":          str (si erreur/skip),
             }
    """
    # ── Vérification credentials ─────────────────────────────────────────────
    if not access_token or not location_id:
        msg = (
            "Credentials HubRise absents pour ce snack. "
            "Connectez HubRise via /hubrise/connect pour activer le push."
        )
        logger.warning("⚠️  [HubRise] %s", msg)
        return {"status": "skipped", "message": msg}

    # ── Construction du payload ──────────────────────────────────────────────
    try:
        payload = _build_payload(order)
    except Exception as e:
        logger.error("❌ [HubRise] Erreur construction payload : %s", e)
        return {"status": "error", "message": f"Payload error: {e}"}

    # ── Appel API HubRise ────────────────────────────────────────────────────
    endpoint = f"{HUBRISE_API_BASE}/locations/{location_id}/orders"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }

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
