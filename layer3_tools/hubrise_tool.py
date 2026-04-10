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
      │         {status: "new", payment: sur_place, items: [...]}
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
  - Paiement sur place : payment_type = "cash" (valeur requise par l'API HubRise), status = "new".
  - Mapping Gemini → HubRise : name, qty, price avec defaults sûrs.
"""

import copy
import logging
import threading
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

# ─── C1 — Locks anti double-tap par (phone, snack_id) ─────────────────────────
# Empêche deux threads concurrents (double-clic client) de créer deux commandes
# identiques. Non-bloquant : le second thread est éjecté immédiatement.

_order_locks: dict = {}
_order_locks_meta = threading.Lock()


def _get_order_lock(phone: str, snack_id: str) -> threading.Lock:
    """Retourne (et crée si besoin) un Lock par couple (phone, snack_id)."""
    key = f"{phone}:{snack_id}"
    with _order_locks_meta:
        if key not in _order_locks:
            _order_locks[key] = threading.Lock()
        return _order_locks[key]


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
      - payment.type = "cash"       (valeur API HubRise pour paiement sur place — mode 'unpaid')
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


# =============================================================================
# FINALISATION COMMANDE — Orchestration complète depuis panier Supabase
# =============================================================================

def finalize_cart_order(phone: str, config: dict) -> dict:
    """
    Orchestre la finalisation complète d'une commande client :
      1. Acquiert un lock par (phone, snack_id) — éjecte les double-taps (C1)
      2. Vide le panier immédiatement (ceinture+bretelles anti-doublon)
      3. Crée la commande dans Supabase (create_order, status=pending)
      4. Pousse vers HubRise avec paiement sur place (push_to_hubrise)
      5. Lie l'ID HubRise + met à jour status=confirmed

    Retourne un dict riche incluant le récapitulatif, le total et le
    temps d'attente estimé pour que le webhook puisse envoyer la
    confirmation WhatsApp, l'alerte Telegram et le cart_clear.

    :param phone:  Numéro client au format E.164.
    :param config: Dict issu de supabase_tool.get_snack_config().
    :return: {
        "status":        "ok" | "error",
        "hubrise_ok":    bool,
        "order_id":      str,
        "summary":       str,   # récapitulatif formaté
        "total":         float,
        "items":         list,   # items bruts du panier
        "estimated_wait": str,  # temps d'attente estimé
        "message":       str,   # si erreur
    }
    """
    from layer3_tools.supabase_tool import (
        checkout_cart, cart_get, cart_clear, create_order, link_hubrise_order, update_order_status,
    )

    snack_id    = str(config.get("id") or config.get("snack_id", "")).strip()
    nom_resto   = config.get("nom_resto") or config.get("name", "Le Snack")
    hr_token    = str(config.get("hubrise_access_token", "") or "").strip()
    hr_loc      = str(config.get("hubrise_location_id", "") or "").strip()

    # ── C1 — Lock anti double-tap ────────────────────────────────────────────
    lock = _get_order_lock(phone, snack_id)
    if not lock.acquire(blocking=False):
        logger.warning(
            "⚠️  [C1] Double-tap détecté pour phone=%s snack=%s — commande ignorée.", phone, snack_id
        )
        return {"status": "error", "message": "Commande déjà en cours de traitement"}

    try:
        # ── Ceinture+bretelles atomiques : Supabase atomic DELETE ──────────────
        # Le thread qui arrive ici vide et récupère le panier en 1 seule requête SQL.
        # Un second thread qui contournerait le lock (ex: 2 instances Railway)
        # obtiendra `[]` (panier vide) de la base de données et s'arrêtera là.
        items = checkout_cart(phone, snack_id)
        if not items:
            return {"status": "error", "message": "Panier vide"}

        parsed_items = [
            {"name": it["name"], "qty": it["qty"], "price": it.get("price")}
            for it in items
        ]

        # 2. Créer la commande dans Supabase (status=pending, paiement sur place)
        order_id: Optional[str] = None
        try:
            res = create_order(
                snack_id=snack_id,
                data={"customer_phone": phone, "items": parsed_items, "status": "pending"},
            )
            # Guard : si create_order retourne un dict d'erreur sans lever,
            # on stoppe immédiatement pour ne pas continuer avec order_id=None.
            if res.get("status") == "error":
                err_msg = res.get("message", "create_order a échoué")
                logger.error("❌ finalize_cart_order : create_order erreur silencieuse : %s", err_msg)
                return {"status": "error", "message": err_msg}
            order_id = res.get("row", {}).get("id")
            if not order_id:
                logger.error("❌ finalize_cart_order : create_order n'a pas retourné d'id")
                return {"status": "error", "message": "create_order n'a pas retourné d'id"}
            logger.info("✅ finalize_cart_order : commande créée id=%s", order_id)
        except Exception as e:
            logger.error("❌ finalize_cart_order : create_order échoué : %s", e)
            return {"status": "error", "message": str(e)}

        # 3. Push HubRise (paiement sur place)
        hubrise_ok = False
        hubrise_id = ""
        try:
            hr_result = push_to_hubrise(
                order={
                    "id":             order_id,
                    "customer_phone": phone,
                    "items":          parsed_items,
                    "status":         "pending",
                },
                access_token=hr_token,
                location_id=hr_loc,
                snack_name=nom_resto,
            )
            if hr_result.get("status") == "created":
                hubrise_id = hr_result.get("hubrise_order_id", "")
                link_hubrise_order(order_id, hubrise_id)
                update_order_status(order_id=order_id, status="confirmed", snack_id=snack_id)
                hubrise_ok = True
                logger.info("✅ finalize_cart_order : HubRise push OK | hr_id=%s", hubrise_id)
            else:
                logger.warning("⚠️  finalize_cart_order : HubRise push non créé : %s", hr_result)
        except Exception as e:
            logger.warning("⚠️  finalize_cart_order : push_to_hubrise échoué (non bloquant) : %s", e)

        # 4. Résumé + total
        summary_lines = [
            f"  • {it['qty']}x {it['name']}" + (f" — {it['price']:.2f}€" if it.get("price") else "")
            for it in items
        ]
        summary = "\n".join(summary_lines)
        total   = sum((it.get("price") or 0) * it["qty"] for it in items)

        # 5. Estimation temps d'attente (heuristique basée sur le nombre d'articles)
        total_items = sum(it["qty"] for it in items)
        if total_items <= 2:
            estimated_wait = "10-15 min"
        elif total_items <= 5:
            estimated_wait = "15-20 min"
        else:
            estimated_wait = "20-30 min"

        return {
            "status":         "ok",
            "hubrise_ok":     hubrise_ok,
            "order_id":       order_id or "",
            "summary":        summary,
            "total":          total,
            "items":          items,
            "estimated_wait": estimated_wait,
        }

    finally:
        lock.release()


# =============================================================================
# SYNCHRONISATION STOCK — HubRise Catalog → Supabase menu_data
# =============================================================================

def _get_catalog_for_location(access_token: str, location_id: str) -> Optional[dict]:
    """
    Récupère le catalogue HubRise associé à un établissement.

    Flux en deux appels :
      1. GET /locations/{location_id}  → extrait l'id du catalogue lié
      2. GET /catalogs/{catalog_id}    → retourne le catalogue complet

    :return: Dictionnaire du catalogue HubRise ou None en cas d'erreur.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type":  "application/json",
    }

    # ── Étape 1 : récupération de l'id du catalogue via la location ──────────
    try:
        loc_resp = requests.get(
            f"{HUBRISE_API_BASE}/locations/{location_id}",
            headers=headers,
            timeout=10,
        )
        if loc_resp.status_code != 200:
            logger.error(
                "❌ [HubRise] GET /locations/%s → HTTP %s", location_id, loc_resp.status_code
            )
            return None

        loc_data   = loc_resp.json()
        # HubRise retourne soit {"catalog": {"id": "..."}} soit {"catalog_id": "..."}
        catalog_id = (
            loc_data.get("catalog_id")
            or (loc_data.get("catalog") or {}).get("id")
        )

        if not catalog_id:
            logger.warning(
                "⚠️  [HubRise] Aucun catalogue lié à la location '%s'.", location_id
            )
            return None

    except requests.exceptions.Timeout:
        logger.error("⏱️  [HubRise] Timeout lors de GET /locations/%s", location_id)
        return None
    except Exception as exc:
        logger.error("💥 [HubRise] Erreur GET /locations/%s : %s", location_id, exc)
        return None

    # ── Étape 2 : récupération du catalogue complet ───────────────────────────
    try:
        cat_resp = requests.get(
            f"{HUBRISE_API_BASE}/catalogs/{catalog_id}",
            headers=headers,
            timeout=10,
        )
        if cat_resp.status_code != 200:
            logger.error(
                "❌ [HubRise] GET /catalogs/%s → HTTP %s", catalog_id, cat_resp.status_code
            )
            return None

        logger.info("✅ [HubRise] Catalogue récupéré (id=%s)", catalog_id)
        return cat_resp.json()

    except requests.exceptions.Timeout:
        logger.error("⏱️  [HubRise] Timeout lors de GET /catalogs/%s", catalog_id)
        return None
    except Exception as exc:
        logger.error("💥 [HubRise] Erreur GET /catalogs/%s : %s", catalog_id, exc)
        return None


def _extract_unavailable_products(catalog: dict) -> list:
    """
    Extrait les noms des produits indisponibles depuis un catalogue HubRise.

    Un produit est considéré indisponible si TOUS ses SKUs ont `available: false`.
    Cette règle évite de masquer un produit qui a encore une variante disponible.

    :param catalog: Dictionnaire retourné par GET /catalogs/{id}.
    :return: Liste de noms de produits indisponibles (strings).
    """
    products    = catalog.get("data", {}).get("products", [])
    unavailable = []

    for product in products:
        skus = product.get("skus", [])
        if not skus:
            continue

        all_unavailable = all(not sku.get("available", True) for sku in skus)
        if all_unavailable:
            name = product.get("name", "").strip()
            ref  = product.get("ref", "").strip()
            # Priorité au nom (plus lisible pour Gemini), fallback sur ref
            label = name or ref
            if label:
                unavailable.append(label)

    logger.info(
        "📦 [HubRise] Stock sync : %d produit(s) indisponible(s) détecté(s).", len(unavailable)
    )
    return unavailable


def _merge_stock_into_menu_data(menu_data: Optional[dict], unavailable: list) -> dict:
    """
    Injecte la liste de rupture de stock dans menu_data sans altérer la structure existante.

    Ajoute ou remplace UNIQUEMENT la clé '_out_of_stock' (liste de noms).
    Toutes les autres clés (catégories, produits, prix, etc.) sont préservées à l'identique.

    :param menu_data:    Catalogue JSONB existant (peut être None).
    :param unavailable:  Liste de noms de produits indisponibles.
    :return: Copie profonde de menu_data avec '_out_of_stock' mis à jour.
    """
    updated = copy.deepcopy(menu_data) if menu_data else {}
    updated["_out_of_stock"] = unavailable
    return updated


def sync_stock_with_supabase(snack_id: str) -> dict:
    """
    Synchronise la disponibilité des produits HubRise vers Supabase (menu_data).

    Flux complet :
      1. Récupère les credentials HubRise depuis Supabase (access_token, location_id).
      2. Appelle l'API HubRise /catalog pour ce snack.
      3. Identifie les produits avec available=false sur tous leurs SKUs.
      4. Met à jour menu_data._out_of_stock dans Supabase — sans toucher au reste du catalogue.

    Gemini respecte automatiquement cette liste via son system prompt
    (voir parse_order_skill et generate_upsell_skill dans gemini_tool.py).

    :param snack_id: UUID du restaurant (table snacks).
    :return: {
        "status":               "synced" | "skipped" | "error",
        "unavailable_count":    int,
        "unavailable_products": list[str],
        "db_update":            dict,
    }
    """
    # Import local pour éviter la dépendance circulaire hubrise_tool ↔ supabase_tool
    from layer3_tools.supabase_tool import get_snack_config, update_snack_menu_data

    # ── Étape 1 : récupération des credentials ────────────────────────────────
    try:
        config = get_snack_config(snack_id)
    except Exception as exc:
        logger.error("❌ [StockSync] get_snack_config(%s) : %s", snack_id, exc)
        return {"status": "error", "message": f"Snack introuvable : {exc}"}

    access_token = str(config.get("hubrise_access_token") or "").strip()
    location_id  = str(config.get("hubrise_location_id")  or "").strip()

    if not access_token or not location_id:
        msg = (
            f"Credentials HubRise absents pour snack '{snack_id}'. "
            "Connectez HubRise via /hubrise/connect."
        )
        logger.warning("⚠️  [StockSync] %s", msg)
        return {"status": "skipped", "message": msg}

    # ── Étape 2 : récupération du catalogue ───────────────────────────────────
    catalog = _get_catalog_for_location(access_token, location_id)
    if catalog is None:
        return {
            "status":  "error",
            "message": "Catalogue HubRise indisponible (voir logs pour détails).",
        }

    # ── Étape 3 : extraction des produits indisponibles ───────────────────────
    unavailable = _extract_unavailable_products(catalog)

    # ── Étape 4 : mise à jour Supabase ────────────────────────────────────────
    current_menu_data = config.get("menu_data")
    updated_menu_data = _merge_stock_into_menu_data(current_menu_data, unavailable)
    db_result         = update_snack_menu_data(snack_id, updated_menu_data)

    logger.info(
        "✅ [StockSync] snack=%s | indisponibles=%d | db=%s",
        snack_id, len(unavailable), db_result.get("status"),
    )

    return {
        "status":               "synced",
        "unavailable_count":    len(unavailable),
        "unavailable_products": unavailable,
        "db_update":            db_result,
    }
