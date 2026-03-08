"""
Layer 3 — Tools : Supabase Connector (Snack-Flow)
==================================================
Connecteur principal vers la base de données Supabase (PostgreSQL).
Remplace à terme :
  - gsheets_tool.py    → tables snacks + orders
  - crm_tool.py (SQLite) → table customers + interactions

Architecture Multi-Tenant :
  - Chaque enregistrement porte un snack_id (isolation par tenant).
  - Row Level Security (RLS) activable côté Supabase pour isolation forte.

Tables gérées :
  - snacks        : configuration des restaurants (ex-onglet RESTOS)
  - orders        : journal des commandes (ex-onglet COMMANDES)
  - customers     : profil client CRM (ex-SQLite clients)
  - interactions  : historique des appels IVR (ex-SQLite interactions)

Principes :
  - Zéro ORM lourd : uniquement supabase-py (wrapper léger PostgREST).
  - Self-Healing : les erreurs sont catchées et loguées sans faire planter le flux.
  - Schema-First : les constantes TABLE_* sont la source de vérité.
  - Formatage E.164 : normalisé en amont (phone_tool) avant tout INSERT.

Variables .env requises :
  SUPABASE_URL          https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY  eyJh... (service_role key — côté serveur uniquement)
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ─── Logger dédié ─────────────────────────────────────────────────────────────

logger = logging.getLogger("snack_flow.supabase")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(levelname)s | supabase_tool | %(message)s")
    )
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

# ─── Noms des tables (source de vérité) ───────────────────────────────────────

TABLE_SNACKS       = "snacks"
TABLE_ORDERS       = "orders"
TABLE_CUSTOMERS    = "customers"
TABLE_INTERACTIONS = "interactions"

# ─── Client Supabase (singleton) ──────────────────────────────────────────────

_supabase_client: Optional[Client] = None


def get_client() -> Client:
    """
    Retourne le client Supabase initialisé (singleton).
    Lève une RuntimeError si les variables d'env sont absentes.
    """
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError(
            "❌ SUPABASE_URL et SUPABASE_SERVICE_KEY sont requis dans le fichier .env\n"
            "   Récupérez-les dans : Supabase Dashboard → Settings → API"
        )

    _supabase_client = create_client(url, key)
    logger.info("✅ Client Supabase initialisé → %s", url)
    return _supabase_client


# =============================================================================
# TABLE : snacks — Configuration des restaurants (remplace GSheets RESTOS)
# =============================================================================

def get_snack_config(snack_id: str) -> dict:
    """
    Récupère la configuration complète d'un restaurant depuis la table 'snacks'.
    Équivalent de gsheets_tool.get_snack_config().

    :param snack_id: Identifiant unique du restaurant (ex: "SNACK_PARIS_01").
    :return: Dictionnaire de configuration complet.
    :raises KeyError: Si le snack_id est introuvable.
    """
    try:
        sb = get_client()
        response = (
            sb.table(TABLE_SNACKS)
            .select("*")
            .eq("snack_id", snack_id.strip())
            .single()
            .execute()
        )
        if response.data:
            logger.info("✅ Config snack chargée : %s", snack_id)
            return response.data
        raise KeyError(
            f"snack_id '{snack_id}' introuvable dans la table '{TABLE_SNACKS}'."
        )
    except KeyError:
        raise
    except Exception as e:
        logger.error("❌ get_snack_config(%s) : %s", snack_id, e)
        raise


def list_all_snacks() -> list:
    """
    Retourne la liste de tous les restaurants actifs depuis la table 'snacks'.
    Équivalent de restaurant_registry.list_all_restaurants().

    :return: Liste de dictionnaires (un par restaurant).
    """
    try:
        sb = get_client()
        response = (
            sb.table(TABLE_SNACKS)
            .select("*")
            .order("snack_id")
            .execute()
        )
        restaurants = response.data or []
        logger.info("✅ %d restaurant(s) chargé(s) depuis Supabase.", len(restaurants))
        return restaurants
    except Exception as e:
        logger.error("❌ list_all_snacks : %s", e)
        return []


def upsert_snack(
    snack_id: str,
    nom_resto: str,
    whatsapp_phone_id: str,
    whatsapp_token: str,
    menu_url: str = "",
    loyalty_threshold: int = 5,
    resto_phone: str = "",
) -> dict:
    """
    Crée ou met à jour un restaurant dans la table 'snacks'.
    Idempotent grâce au ON CONFLICT sur snack_id (clé primaire).

    :return: Enregistrement créé/mis à jour.
    """
    try:
        sb = get_client()
        data = {
            "snack_id":           snack_id.strip(),
            "nom_resto":          nom_resto.strip(),
            "whatsapp_phone_id":  whatsapp_phone_id.strip(),
            "whatsapp_token":     whatsapp_token.strip(),
            "menu_url":           menu_url.strip(),
            "loyalty_threshold":  loyalty_threshold,
            "resto_phone":        resto_phone.strip(),
            "updated_at":         datetime.now(timezone.utc).isoformat(),
        }
        response = (
            sb.table(TABLE_SNACKS)
            .upsert(data, on_conflict="snack_id")
            .execute()
        )
        result = response.data[0] if response.data else data
        logger.info("✅ Snack upsert : %s (%s)", snack_id, nom_resto)
        return result
    except Exception as e:
        logger.error("❌ upsert_snack(%s) : %s", snack_id, e)
        return {"error": str(e)}


# =============================================================================
# TABLE : orders — Journal des commandes (remplace GSheets COMMANDES)
# =============================================================================

def log_order(
    snack_id: str,
    customer_phone: str,
    order_details: str = "",
    status: str = "Lien envoyé",
) -> dict:
    """
    Insère une nouvelle ligne dans la table 'orders'.
    Équivalent de gsheets_tool.log_order().

    :param snack_id:       Identifiant du restaurant (FK vers snacks).
    :param customer_phone: Numéro client au format E.164.
    :param order_details:  Description libre de la commande.
    :param status:         "Lien envoyé" | "Échec" | "En attente".
    :return: Ligne insérée ou dict d'erreur.
    """
    try:
        sb = get_client()
        row = {
            "snack_id":       snack_id.strip(),
            "customer_phone": customer_phone.strip(),
            "order_details":  order_details,
            "status":         status,
            "created_at":     datetime.now(timezone.utc).isoformat(),
        }
        response = sb.table(TABLE_ORDERS).insert(row).execute()
        result = response.data[0] if response.data else row
        logger.info("✅ Order loguée : %s | %s | %s", snack_id, customer_phone, status)
        return {"status": "success", "row": result}
    except Exception as e:
        logger.error("❌ log_order : %s", e)
        return {"status": "error", "message": str(e)}


def get_orders(snack_id: str, limit: int = 100) -> list:
    """
    Retourne les dernières commandes d'un restaurant (tri DESC).

    :param snack_id: Identifiant du restaurant.
    :param limit:    Nombre maximum de résultats (défaut 100).
    :return: Liste de commandes.
    """
    try:
        sb = get_client()
        response = (
            sb.table(TABLE_ORDERS)
            .select("*")
            .eq("snack_id", snack_id.strip())
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or []
    except Exception as e:
        logger.error("❌ get_orders(%s) : %s", snack_id, e)
        return []


# =============================================================================
# TABLE : customers — CRM client (remplace SQLite clients)
# =============================================================================

def upsert_customer(
    phone_e164: str,
    snack_id: str,
    ivr_choice: str = "",
) -> dict:
    """
    Crée ou met à jour le profil d'un client.
    Equivalent de crm_tool.upsert_client().
    - Première fois → INSERT
    - Fois suivantes → UPDATE last_contact + total_orders si ivr_choice == "1"

    :param phone_e164: Numéro client E.164.
    :param snack_id:   Identifiant du restaurant.
    :param ivr_choice: Choix IVR ("1" ou "2").
    :return: Profil client mis à jour.
    """
    try:
        sb = get_client()
        now = datetime.now(timezone.utc).isoformat()
        is_order = ivr_choice.strip() == "1"

        # Vérifie si le client existe déjà
        existing = (
            sb.table(TABLE_CUSTOMERS)
            .select("*")
            .eq("phone_e164", phone_e164.strip())
            .eq("snack_id", snack_id.strip())
            .execute()
        )

        if existing.data:
            # Mise à jour
            update_data: dict = {"last_contact": now}
            if is_order:
                current_orders = existing.data[0].get("total_orders", 0) or 0
                update_data["total_orders"] = current_orders + 1

            response = (
                sb.table(TABLE_CUSTOMERS)
                .update(update_data)
                .eq("phone_e164", phone_e164.strip())
                .eq("snack_id", snack_id.strip())
                .execute()
            )
            result = response.data[0] if response.data else existing.data[0]
            logger.info("✅ Customer mis à jour : %s → %s", phone_e164, snack_id)
        else:
            # Insertion
            insert_data = {
                "phone_e164":            phone_e164.strip(),
                "snack_id":              snack_id.strip(),
                "first_contact":         now,
                "last_contact":          now,
                "total_orders":          1 if is_order else 0,
                "remarketing_eligible":  True,
            }
            response = (
                sb.table(TABLE_CUSTOMERS)
                .insert(insert_data)
                .execute()
            )
            result = response.data[0] if response.data else insert_data
            logger.info("✅ Nouveau customer CRM : %s → %s", phone_e164, snack_id)

        return result

    except Exception as e:
        logger.error("❌ upsert_customer(%s, %s) : %s", phone_e164, snack_id, e)
        return {"error": str(e)}


def get_customer(phone_e164: str, snack_id: str) -> Optional[dict]:
    """
    Retourne le profil d'un client, ou None s'il n'existe pas.
    """
    try:
        sb = get_client()
        response = (
            sb.table(TABLE_CUSTOMERS)
            .select("*")
            .eq("phone_e164", phone_e164.strip())
            .eq("snack_id", snack_id.strip())
            .single()
            .execute()
        )
        return response.data or None
    except Exception:
        return None


def check_customer_loyalty(snack_id: str, customer_phone: str) -> str:
    """
    Détermine le statut de fidélité d'un client.
    Équivalent de gsheets_tool.check_customer_loyalty().

    Stratégie :
      1. Récupère loyalty_threshold depuis snacks.
      2. Compare total_orders du customer au seuil.

    :return: "LOYAL" si commandes >= seuil, sinon "NEW".
    """
    try:
        config = get_snack_config(snack_id)
        threshold = int(config.get("loyalty_threshold", 0) or 0)

        customer = get_customer(customer_phone, snack_id)
        if not customer:
            return "NEW"

        total_orders = int(customer.get("total_orders", 0) or 0)
        status = "LOYAL" if (threshold > 0 and total_orders >= threshold) else "NEW"

        logger.info(
            "📊 Fidélité [%s] %s : %d commande(s) / seuil %d → %s",
            snack_id, customer_phone, total_orders, threshold, status,
        )
        return status

    except Exception as e:
        logger.error("❌ check_customer_loyalty : %s", e)
        return "NEW"


def get_remarketing_targets(snack_id: str, inactive_days: int = 30) -> list:
    """
    Retourne les clients éligibles au remarketing (inactifs depuis N jours).
    Équivalent de crm_tool.get_remarketing_targets().
    """
    try:
        sb = get_client()
        # Supabase PostgREST : filtre sur last_contact via lt (less than)
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff -= timedelta(days=inactive_days)

        response = (
            sb.table(TABLE_CUSTOMERS)
            .select("*")
            .eq("snack_id", snack_id.strip())
            .eq("remarketing_eligible", True)
            .gte("total_orders", 1)
            .lt("last_contact", cutoff.isoformat())
            .order("last_contact")
            .execute()
        )
        targets = response.data or []
        logger.info(
            "📊 Remarketing '%s' : %d client(s) inactif(s) depuis %dj",
            snack_id, len(targets), inactive_days,
        )
        return targets
    except Exception as e:
        logger.error("❌ get_remarketing_targets : %s", e)
        return []


# =============================================================================
# TABLE : interactions — Historique IVR (remplace SQLite interactions)
# =============================================================================

def log_interaction(
    phone_e164: str,
    snack_id: str,
    ivr_choice: str,
    sms_status: str = "N/A",
    transfer_status: str = "N/A",
) -> dict:
    """
    Enregistre une interaction IVR dans la table 'interactions'.
    Équivalent de crm_tool.log_interaction().

    :return: Interaction insérée ou dict d'erreur.
    """
    try:
        sb = get_client()
        row = {
            "phone_e164":      phone_e164.strip(),
            "snack_id":        snack_id.strip(),
            "ivr_choice":      ivr_choice,
            "sms_status":      sms_status,
            "transfer_status": transfer_status,
            "created_at":      datetime.now(timezone.utc).isoformat(),
        }
        response = sb.table(TABLE_INTERACTIONS).insert(row).execute()
        result = response.data[0] if response.data else row
        logger.info("✅ Interaction loguée : %s | %s | %s", snack_id, phone_e164, ivr_choice)
        return result
    except Exception as e:
        logger.error("❌ log_interaction : %s", e)
        return {"error": str(e)}


# =============================================================================
# HEALTH CHECK — Vérifie la connexion Supabase
# =============================================================================

def health_check() -> dict:
    """
    Vérifie que la connexion Supabase est opérationnelle.
    Utilisable par le /health endpoint Flask.

    :return: {"status": "ok"|"error", "message": str}
    """
    try:
        sb = get_client()
        # Requête légère : compte le nombre de snacks
        response = sb.table(TABLE_SNACKS).select("snack_id", count="exact").execute()
        count = response.count or 0
        logger.info("✅ Supabase health check OK — %d snack(s) en base.", count)
        return {"status": "ok", "snacks_count": count}
    except Exception as e:
        logger.error("❌ Supabase health check FAILED : %s", e)
        return {"status": "error", "message": str(e)}


# =============================================================================
# TEST STANDALONE
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("   Snack-Flow — Supabase Tool — Self-Test")
    print("=" * 60)

    print("\n[1] Health check Supabase...")
    result = health_check()
    print("   →", result)

    print("\n[2] Liste des snacks...")
    snacks = list_all_snacks()
    print(f"   → {len(snacks)} restaurant(s) trovué(s)")
    for s in snacks:
        print(f"     • [{s.get('snack_id')}] {s.get('nom_resto')}")

    print("\n[3] Test upsert customer...")
    customer = upsert_customer("+33785557054", "SNACK_TEST_01", ivr_choice="1")
    print("   →", customer)

    print("\n[4] Test log order...")
    order = log_order("SNACK_TEST_01", "+33785557054", "Test Supabase", "Lien envoyé")
    print("   →", order)

    print("\n" + "=" * 60)
    print("   ✅ Self-Test terminé")
    print("=" * 60)
