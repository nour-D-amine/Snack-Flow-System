"""
Layer 3 — Tools : Supabase Connector (Snack-Flow v2.0 Full-WhatsApp)
=====================================================================
Connecteur principal vers la base de données Supabase (PostgreSQL).
Source de vérité unique du système — remplace GSheets, SQLite, Notion.

Architecture Multi-Tenant :
  - Chaque enregistrement porte un snack_id (isolation par tenant).
  - Row Level Security (RLS) activé côté Supabase.

Tables gérées :
  - snacks        : configuration des restaurants (credentials WA, menu_url)
  - orders        : journal des commandes WhatsApp
  - customers     : profil client CRM (fidélité, remarketing)
  - interactions  : historique des échanges WhatsApp

Principes :
  - Zéro ORM lourd : uniquement supabase-py (wrapper léger PostgREST).
  - Self-Healing : les erreurs sont catchées et loguées sans faire planter le flux.
  - Schema-First : les constantes TABLE_* sont la source de vérité.
  - Formatage E.164 : normalisé en amont (phone_tool) avant tout INSERT.

Variables .env requises :
  SUPABASE_URL               https://xxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY  eyJh... (service_role key — côté serveur uniquement)
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

TABLE_SNACKS        = "snacks"
TABLE_ORDERS        = "orders"
TABLE_CUSTOMERS     = "customers"

# ─── Client Supabase (Singleton class) ────────────────────────────────────────


class SupabaseClient:
    """
    Singleton thread-safe du client Supabase.

    Usage :
        sb = SupabaseClient.instance()
        sb.table("snacks").select("*").execute()

    Variables .env requises :
        SUPABASE_URL              https://xxxx.supabase.co
        SUPABASE_SERVICE_ROLE_KEY eyJh...  (service_role key — serveur uniquement)
    """

    _instance: Optional["SupabaseClient"] = None
    _client: Optional[Client] = None
    _lock = __import__("threading").Lock()

    def __new__(cls) -> "SupabaseClient":
        with cls._lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                url = os.getenv("SUPABASE_URL", "").strip()
                key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
                if not url or not key:
                    raise RuntimeError(
                        "❌ SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY sont requis dans .env\n"
                        "   Récupérez-les dans : Supabase Dashboard → Settings → API"
                    )
                obj._client = create_client(url, key)   # assign to local obj first
                cls._instance = obj                     # commit singleton only after success
                logger.info("✅ SupabaseClient (singleton) initialisé → %s", url)
        return cls._instance

    @classmethod
    def instance(cls) -> "SupabaseClient":
        """Retourne l'instance singleton (crée si nécessaire)."""
        return cls()

    def table(self, name: str):
        """Proxy vers supabase_client.table()."""
        return self._client.table(name)  # type: ignore[union-attr]

    @property
    def raw(self) -> Client:
        """Accès direct au client Supabase natif (usage avancé)."""
        return self._client  # type: ignore[return-value]


# ─── Helpers backward-compat ──────────────────────────────────────────────────

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
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError(
            "❌ SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY sont requis dans le fichier .env\n"
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
    def _enrich(config: dict) -> dict:
        """Injecte les alias rétrocompat pour whatsapp_tool.py v2."""
        config["snack_id"]          = config.get("id")
        config["nom_resto"]         = config.get("name")
        config["whatsapp_phone_id"] = (
            config.get("whatsapp_phone_number_id")
            or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        )
        if not config["whatsapp_phone_id"]:
            logger.warning("⚠️  get_snack_config : whatsapp_phone_id vide pour '%s'", sid)
        config["whatsapp_token"]    = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        if not config["whatsapp_token"]:
            logger.warning("⚠️  get_snack_config : WHATSAPP_ACCESS_TOKEN non configuré !")
        config["menu_url"]          = os.getenv("MENU_URL", "https://le-menu.app")
        config["loyalty_threshold"] = 3
        config["resto_phone"]       = os.getenv("RESTO_PHONE", "+33600000000")
        return config

    try:
        sb  = SupabaseClient.instance()
        sid = snack_id.strip()

        # Tentative 1 : lookup par UUID (id) — chemin nominal
        try:
            response = (
                sb.table(TABLE_SNACKS)
                .select("*")
                .eq("id", sid)
                .single()
                .execute()
            )
            if response.data:
                logger.info("✅ Config snack chargée (by id) : %s", sid)
                return _enrich(response.data)
        except Exception:
            pass  # single() lève si 0 résultat → on essaie le fallback

        # Tentative 2 : lookup par name (fallback dev / DEFAULT_SNACK_ID lisible)
        try:
            response2 = (
                sb.table(TABLE_SNACKS)
                .select("*")
                .eq("name", sid)
                .single()
                .execute()
            )
            if response2.data:
                logger.warning(
                    "⚠️  get_snack_config : '%s' résolu via name, pas un UUID. "
                    "Mettez à jour DEFAULT_SNACK_ID dans .env avec l'UUID Supabase.", sid
                )
                return _enrich(response2.data)
        except Exception:
            pass

        raise KeyError(
            f"snack_id '{sid}' introuvable dans Supabase (ni par id, ni par name)."
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
        sb = SupabaseClient.instance()
        response = (
            sb.table(TABLE_SNACKS)
            .select("*")
            .order("id")
            .execute()
        )
        restaurants = response.data or []
        logger.info("✅ %d restaurant(s) chargé(s) depuis Supabase.", len(restaurants))
        return restaurants
    except Exception as e:
        logger.error("❌ list_all_snacks : %s", e)
        return []


def get_snack_by_phone_id(phone_id: str) -> Optional[dict]:
    """
    Authentifie un tenant entrant via son whatsapp_phone_number_id.

    Utilisé par le webhook Flask pour router chaque requête Meta vers
    le bon restaurant. Retourne None si introuvable ou inactif.

    :param phone_id: Valeur de metadata.phone_number_id reçue de Meta.
    :return: Enregistrement snack complet (dict) ou None.
    """
    try:
        sb = SupabaseClient.instance()
        response = (
            sb.table(TABLE_SNACKS)
            .select("*")
            .eq("whatsapp_phone_number_id", phone_id.strip())
            .eq("is_active", True)
            .single()
            .execute()
        )
        if response.data:
            logger.info("✅ Tenant authentifié : phone_number_id=%s → snack id=%s",
                        phone_id, response.data.get("id"))
            return response.data
        logger.warning("⚠️  [UNAUTHORIZED_SNACK] phone_number_id=%s → aucun snack actif", phone_id)
        return None
    except Exception as e:
        logger.error("❌ get_snack_by_phone_id(%s) : %s", phone_id, e)
        return None


def create_order(snack_id: str, data: dict) -> dict:
    """
    Enregistre une nouvelle commande dans la table 'orders' (schéma init.sql v3).

    :param snack_id: UUID du restaurant (PK de la table snacks).
    :param data: Dictionnaire contenant au minimum :
                   - customer_phone (str E.164)
                   - items          (list de dicts)
                   - status         (str, défaut "pending")
    :return: Ligne insérée ou dict d'erreur.
    """
    try:
        sb = SupabaseClient.instance()
        row = {
            "snack_id":       snack_id.strip(),
            "customer_phone": data.get("customer_phone", "").strip(),
            "items":          data.get("items", []),
            "status":         data.get("status", "pending"),
        }
        response = sb.table(TABLE_ORDERS).insert(row).execute()
        result = response.data[0] if response.data else row
        logger.info("✅ create_order : snack=%s | phone=%s | status=%s",
                    snack_id, row["customer_phone"], row["status"])
        return {"status": "success", "row": result}
    except Exception as e:
        logger.error("❌ create_order(%s) : %s", snack_id, e)
        return {"status": "error", "message": str(e)}


def upsert_snack(
    name: str,
    whatsapp_phone_number_id: str,
    is_active: bool = True,
    # Legacy params kept for backward-compat (ignored in v3 schema)
    snack_id: str = "",
    nom_resto: str = "",
    whatsapp_phone_id: str = "",
    whatsapp_token: str = "",
    menu_url: str = "",
    loyalty_threshold: int = 5,
    resto_phone: str = "",
) -> dict:
    """
    Crée ou met à jour un restaurant dans la table 'snacks' (schéma v3.0).

    Schéma v3 :
      - name                     : Nom du restaurant
      - whatsapp_phone_number_id : ID Meta (clé d'authentification tenant)
      - is_active                : Actif/inactif

    :return: Enregistrement créé/mis à jour (dict avec 'id' UUID).
    """
    # Résolution du nom (compat legacy)
    resolved_name = name.strip() if name.strip() else nom_resto.strip()
    resolved_phone_id = (
        whatsapp_phone_number_id.strip()
        if whatsapp_phone_number_id.strip()
        else whatsapp_phone_id.strip()
    )

    # Avertissement explicite : ces colonnes n'existent pas dans le schéma v3 (init.sql).
    # Si vous en avez besoin, ajoutez-les via une migration SQL avant de les utiliser ici.
    _legacy_with_values = {
        k: v for k, v in {
            "menu_url": menu_url,
            "loyalty_threshold": loyalty_threshold if loyalty_threshold != 5 else None,
            "resto_phone": resto_phone,
        }.items() if v
    }
    if _legacy_with_values:
        logger.warning(
            "⚠️  upsert_snack : paramètre(s) ignoré(s) — absent(s) du schéma v3 : %s. "
            "Ces valeurs NE SONT PAS enregistrées en base. "
            "Créez une migration SQL pour ajouter ces colonnes.", list(_legacy_with_values.keys())
        )

    try:
        sb = SupabaseClient.instance()
        data = {
            "name":                     resolved_name,
            "whatsapp_phone_number_id": resolved_phone_id,
            "is_active":                is_active,
        }
        response = (
            sb.table(TABLE_SNACKS)
            .upsert(data, on_conflict="whatsapp_phone_number_id")
            .execute()
        )
        result = response.data[0] if response.data else data
        logger.info("✅ Snack upsert v3 : '%s' | phone_id=%s", resolved_name, resolved_phone_id)
        return result
    except Exception as e:
        logger.error("❌ upsert_snack('%s') : %s", resolved_name, e)
        return {"error": str(e)}


# =============================================================================
# TABLE : orders — Journal des commandes (remplace GSheets COMMANDES)
# =============================================================================

def log_order(
    snack_id: str,
    customer_phone: str,
    order_details: str = "",
    status: str = "pending",
    items: Optional[list] = None,
) -> dict:
    """
    Insère une nouvelle ligne dans la table 'orders' (schéma v3.0 — JSONB items).

    :param snack_id:       UUID du restaurant (FK vers snacks.id).
    :param customer_phone: Numéro client au format E.164.
    :param order_details:  Texte brut de la commande (converti en items JSONB si items=None).
    :param status:         "pending" | "confirmed" | "failed" | "cancelled".
    :param items:          Liste JSONB structurée [{"name": ..., "qty": ...}].
                           Si None (legacy), sera encapsulé depuis order_details.
    :return: Ligne insérée ou dict d'erreur.
    """
    # Validation des valeurs status acceptées par la contrainte CHECK
    _valid_statuses = {"pending", "confirmed", "failed", "cancelled"}
    if status not in _valid_statuses:
        logger.warning("⚠️  log_order : statut invalide '%s' → forcé à 'pending'", status)
        status = "pending"

    # Conversion order_details → JSONB items si items non fournis
    if items is None:
        items = [{"name": order_details or "Commande WhatsApp", "qty": 1}]

    try:
        sb = SupabaseClient.instance()
        row = {
            "snack_id":       snack_id.strip(),
            "customer_phone": customer_phone.strip(),
            "items":          items,
            "status":         status,
        }
        response = sb.table(TABLE_ORDERS).insert(row).execute()
        result = response.data[0] if response.data else row
        logger.info("✅ Order loguée v3 : %s | %s | %s", snack_id, customer_phone, status)
        return {"status": "success", "row": result}
    except Exception as e:
        logger.error("❌ log_order : %s", e)
        return {"status": "error", "message": str(e)}


def update_order_status(order_id: str, status: str, snack_id: str = "") -> dict:
    """
    Met à jour le statut d'une commande existante.

    :param order_id: UUID de la commande (retourné par log_order / create_order).
    :param status:   "pending" | "confirmed" | "failed" | "cancelled".
    :param snack_id: (optionnel) UUID du tenant — filtre de sécurité multi-tenant.
    :return: Ligne mise à jour ou dict d'erreur.
    """
    _valid_statuses = {"pending", "confirmed", "failed", "cancelled"}
    if status not in _valid_statuses:
        logger.warning("⚠️  update_order_status : statut invalide '%s' → forcé à 'pending'", status)
        status = "pending"
    try:
        sb = SupabaseClient.instance()
        query = (
            sb.table(TABLE_ORDERS)
            .update({"status": status})
            .eq("id", order_id)
        )
        if snack_id:
            query = query.eq("snack_id", snack_id.strip())
        response = query.execute()
        result = response.data[0] if response.data else {"id": order_id, "status": status}
        logger.info("✅ update_order_status : id=%s → %s", order_id, status)
        return {"status": "success", "row": result}
    except Exception as e:
        logger.error("❌ update_order_status(%s) : %s", order_id, e)
        return {"status": "error", "message": str(e)}


def get_orders(snack_id: str, limit: int = 100) -> list:
    """
    Retourne les dernières commandes d'un restaurant (tri DESC).

    :param snack_id: Identifiant du restaurant.
    :param limit:    Nombre maximum de résultats (défaut 100).
    :return: Liste de commandes.
    """
    try:
        sb = SupabaseClient.instance()
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
# TABLE : customers — CRM client
# =============================================================================

def upsert_customer(phone_e164: str, snack_id: str) -> dict:
    """
    Crée ou met à jour le profil CRM d'un client dans la table 'customers'.

    - INSERT la première fois (first_contact = NOW()).
    - UPDATE last_contact + total_orders += 1 les fois suivantes.

    :param phone_e164: Numéro client au format E.164 (ex: "+33785557054").
    :param snack_id:   UUID du restaurant (FK vers snacks.id, ou snack_id texte legacy).
    :return: Profil client créé/mis à jour, ou dict d'erreur.
    """
    try:
        sb  = SupabaseClient.instance()
        now = datetime.now(timezone.utc).isoformat()
        phone = phone_e164.strip()
        sid   = snack_id.strip()

        # Vérifier si le client existe déjà pour ce tenant
        existing = (
            sb.table(TABLE_CUSTOMERS)
            .select("*")
            .eq("phone_e164", phone)
            .eq("snack_id", sid)
            .execute()
        )

        if existing.data:
            # Mise à jour : last_contact + compteur commandes
            current_orders = existing.data[0].get("total_orders", 0) or 0
            response = (
                sb.table(TABLE_CUSTOMERS)
                .update({
                    "last_contact":  now,
                    "total_orders":  current_orders + 1,
                })
                .eq("phone_e164", phone)
                .eq("snack_id",   sid)
                .execute()
            )
            result = response.data[0] if response.data else existing.data[0]
            logger.info("✅ Customer mis à jour : %s → snack=%s", phone, sid)
        else:
            # Insertion
            response = (
                sb.table(TABLE_CUSTOMERS)
                .insert({
                    "phone_e164":           phone,
                    "snack_id":             sid,
                    "first_contact":        now,
                    "last_contact":         now,
                    "total_orders":         1,
                    "remarketing_eligible": True,
                })
                .execute()
            )
            result = response.data[0] if response.data else {}
            logger.info("✅ Nouveau customer CRM : %s → snack=%s", phone, sid)

        return result

    except Exception as e:
        logger.error("❌ upsert_customer(%s, %s) : %s", phone_e164, snack_id, e)
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
        sb = SupabaseClient.instance()
        # Requête légère : compte le nombre de snacks
        response = sb.table(TABLE_SNACKS).select("id", count="exact").execute()
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
    print(f"   → {len(snacks)} restaurant(s) trouvé(s)")
    for s in snacks:
        print(f"     • [id={s.get('id')}] {s.get('name')} | phone_id={s.get('whatsapp_phone_number_id')}")

    print("\n[3] Test create_order (utilise le premier snack si disponible)...")
    if snacks:
        test_snack_id = snacks[0].get("id", "")
        order = create_order(
            snack_id=test_snack_id,
            data={"customer_phone": "+33785557054", "items": [{"name": "Test", "qty": 1}], "status": "pending"},
        )
        print("   →", order)
    else:
        print("   ⚠️  Aucun snack en base — test ignoré.")

    print("\n" + "=" * 60)
    print("   ✅ Self-Test terminé")
    print("=" * 60)
