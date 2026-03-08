"""
gsheets_tool.py — Snack-Flow Master Database Layer (Multi-Tenant)
=================================================================
Unique source of truth pour tous les restaurants (tenants).

Onglets gérés :
  - RESTOS    : Registre de configuration des restaurants.
  - COMMANDES : Journal horodaté de toutes les commandes (tous tenants).

Principes :
  - Schema-First  : Les colonnes sont définies comme constantes.
  - Determinism   : Pas d'hallucination, uniquement les données du Sheet.
  - Speed         : batch_get() pour minimiser les appels API (< 3 s).
  - Self-Healing  : initialize_master_structures() crée les onglets manquants.
"""

import gspread
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
DEFAULT_SNACK_ID = os.getenv("DEFAULT_SNACK_ID", "")

# ✅ Chemin absolu — isolation des chemins (Skill_Safety_Gate)
SERVICE_ACCOUNT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "service_account.json"
)

# ─── Schémas de colonnes (source de vérité) ───────────────────────────────────

RESTOS_HEADERS = [
    "snack_id",           # Identifiant unique du restaurant (ex: "SNACK_PARIS_01")
    "nom_resto",          # Nom affiché (ex: "Le Snack du Coin")
    "whatsapp_phone_id",  # Phone Number ID de l'API WhatsApp Business
    "whatsapp_token",     # Token Bearer pour l'API WhatsApp Business
    "menu_url",           # URL du menu interactif à envoyer par SMS/WhatsApp
    "loyalty_threshold",  # Nb de commandes pour déclencher le statut LOYAL (int)
    "resto_phone",        # Numéro de téléphone public du restaurant (E.164) — pour notifications Option 2
]

COMMANDES_HEADERS = [
    "timestamp",          # ISO 8601 : "2026-02-28T04:34:19"
    "snack_id",           # Référence au restaurant (FK vers RESTOS.snack_id)
    "customer_phone",     # Numéro client au format E.164 (ex: "+33785557054")
    "order_details",      # Description libre ou JSON de la commande
    "status",             # "Lien envoyé" | "Échec" | "En attente"
]

# ─── Client Google Sheets (singleton léger) ───────────────────────────────────

def _get_spreadsheet():
    """Retourne l'objet Spreadsheet authentifié via le compte de service."""
    if not SPREADSHEET_ID:
        raise ValueError(
            "GOOGLE_SHEET_ID manquant. Vérifiez votre fichier .env."
        )
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    return gc.open_by_key(SPREADSHEET_ID)


def _get_or_create_worksheet(sh, title: str, headers: list) -> gspread.Worksheet:
    """
    Retourne un onglet existant ou le crée si absent,
    puis s'assure que la première ligne contient les bons en-têtes.
    """
    try:
        ws = sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows="1000", cols=str(len(headers)))
        print(f"✅ Onglet '{title}' créé.")

    first_row = ws.row_values(1)
    if first_row != headers:
        ws.clear()
        ws.append_row(headers, value_input_option="RAW")
        print(f"✅ En-têtes de '{title}' initialisés : {headers}")
    else:
        print(f"ℹ️  Onglet '{title}' déjà configuré.")

    return ws


# ═══════════════════════════════════════════════════════════════════════════════
# 1. INITIALISATION DU MASTER
# ═══════════════════════════════════════════════════════════════════════════════

def initialize_master_structures() -> dict:
    """
    S'assure de l'existence et de la conformité des deux onglets maîtres :
      - 'RESTOS'    avec ses 6 colonnes de configuration.
      - 'COMMANDES' avec ses 5 colonnes de journal.

    Idempotent : peut être appelé plusieurs fois sans effet de bord.

    :return: Dictionnaire de confirmation { "restos": "ok|created", "commandes": "ok|created" }
    """
    sh = _get_spreadsheet()

    ws_restos    = _get_or_create_worksheet(sh, "RESTOS",    RESTOS_HEADERS)
    ws_commandes = _get_or_create_worksheet(sh, "COMMANDES", COMMANDES_HEADERS)

    return {
        "restos":    "ready",
        "commandes": "ready",
        "spreadsheet_id": SPREADSHEET_ID,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. CONFIGURATION DU SNACK (lecture par tenant)
# ═══════════════════════════════════════════════════════════════════════════════

def get_snack_config(snack_id: str) -> dict:
    """
    Récupère la configuration complète d'un restaurant depuis l'onglet 'RESTOS'.

    Utilise get_all_records() (lecture batch) pour minimiser la latence API.

    :param snack_id: Identifiant unique du restaurant (ex: "SNACK_PARIS_01").
    :return: Dictionnaire complet { snack_id, nom_resto, whatsapp_phone_id,
                                    whatsapp_token, menu_url, loyalty_threshold }.
    :raises KeyError: Si le snack_id est introuvable dans l'onglet RESTOS.
    :raises ValueError: Si GOOGLE_SHEET_ID est absent.
    """
    sh = _get_spreadsheet()
    ws = sh.worksheet("RESTOS")

    # Lecture batch de tout l'onglet en un seul appel API
    records = ws.get_all_records()

    for record in records:
        if str(record.get("snack_id", "")).strip() == snack_id.strip():
            # Cast du seuil de fidélité en entier (robustesse)
            try:
                record["loyalty_threshold"] = int(record.get("loyalty_threshold", 0))
            except (ValueError, TypeError):
                record["loyalty_threshold"] = 0
            return record

    raise KeyError(
        f"❌ snack_id '{snack_id}' introuvable dans l'onglet RESTOS. "
        f"Vérifiez la valeur ou provisionnez ce restaurant via restaurant_registry."
    )


def get_restaurant_config(identifier: str) -> dict:
    """
    Recherche par snack_id OU par resto_phone, avec fallback DEFAULT_SNACK_ID.
    Conforme au protocole Skill_Data_Master ④.

    :param identifier: snack_id (ex: 'SNACK_01') ou numéro E.164 (ex: '+33612345678')
    :return: dict config complet du restaurant
    """
    sh = _get_spreadsheet()
    ws = sh.worksheet("RESTOS")
    records = ws.get_all_records()

    for record in records:
        if (str(record.get("snack_id", "")).strip() == identifier.strip() or
                str(record.get("resto_phone", "")).strip() == identifier.strip()):
            try:
                record["loyalty_threshold"] = int(record.get("loyalty_threshold", 0))
            except (ValueError, TypeError):
                record["loyalty_threshold"] = 0
            return record

    # Fallback DEFAULT_SNACK_ID (Skill_Data_Master ⑤)
    if DEFAULT_SNACK_ID and identifier != DEFAULT_SNACK_ID:
        print(f"⚠️  '{identifier}' introuvable — Fallback → {DEFAULT_SNACK_ID}")
        return get_restaurant_config(DEFAULT_SNACK_ID)

    raise KeyError(
        f"❌ Restaurant '{identifier}' introuvable dans RESTOS et aucun DEFAULT_SNACK_ID valide."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FIDÉLITÉ CLIENT (calcul par tenant + client)
# ═══════════════════════════════════════════════════════════════════════════════

def check_customer_loyalty(snack_id: str, customer_phone: str) -> str:
    """
    Détermine le statut de fidélité d'un client pour un restaurant donné.

    Stratégie :
      1. Récupère le loyalty_threshold depuis get_snack_config() (batch read RESTOS).
      2. Filtre l'onglet COMMANDES par snack_id ET customer_phone via batch_get().
      3. Compare le nombre de commandes au seuil.

    :param snack_id:       Identifiant du restaurant.
    :param customer_phone: Numéro du client au format E.164.
    :return: "LOYAL" si commandes >= loyalty_threshold, sinon "NEW".
    :raises KeyError: Si snack_id inconnu.
    """
    # Étape 1 : Seuil de fidélité (réutilise le batch RESTOS)
    config = get_snack_config(snack_id)
    threshold = config["loyalty_threshold"]

    # Étape 2 : Lecture batch optimisée de l'onglet COMMANDES
    sh = _get_spreadsheet()
    ws = sh.worksheet("COMMANDES")

    # Lecture batch de toutes les colonnes nécessaires en un seul appel
    all_rows = ws.get_all_values()  # [header_row, ...data_rows]

    # Mapping dynamique des colonnes (Skill_Data_Master ②)
    headers = all_rows[0] if all_rows else []
    try:
        snack_col = headers.index("snack_id")
        phone_col = headers.index("customer_phone")
    except ValueError:
        print("⚠️  En-têtes COMMANDES introuvables — fidélité non vérifiable")
        return "NEW"

    # Étape 3 : Comptage des correspondances (skip ligne 0 = en-têtes)
    order_count = 0
    for row in all_rows[1:]:
        row_snack = row[snack_col].strip() if len(row) > snack_col else ""
        row_phone = row[phone_col].strip() if len(row) > phone_col else ""

        if row_snack == snack_id.strip() and row_phone == customer_phone.strip():
            order_count += 1

    status = "LOYAL" if (threshold > 0 and order_count >= threshold) else "NEW"
    print(
        f"📊 Fidélité [{snack_id}] {customer_phone} : "
        f"{order_count} commande(s) / seuil {threshold} → {status}"
    )
    return status


# ═══════════════════════════════════════════════════════════════════════════════
# 4. JOURNAL DES COMMANDES (écriture)
# ═══════════════════════════════════════════════════════════════════════════════

def log_order(
    snack_id: str,
    customer_phone: str,
    order_details: str = "",
    status: str = "Lien envoyé",
) -> dict:
    """
    Ajoute une ligne dans l'onglet 'COMMANDES'.

    :param snack_id:       Identifiant du restaurant.
    :param customer_phone: Numéro du client au format E.164.
    :param order_details:  Description ou JSON de la commande.
    :param status:         "Lien envoyé" | "Échec" | "En attente".
    :return: Dictionnaire de confirmation.
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    row = [now, snack_id, customer_phone, order_details, status]

    try:
        sh = _get_spreadsheet()
        ws = sh.worksheet("COMMANDES")
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"✅ Commande loguée : {snack_id} | {customer_phone} | {status}")
        return {"status": "success", "row": row}
    except Exception as e:
        print(f"❌ Erreur log_order : {e}")
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BLOC DE TEST RAPIDE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("   Snack-Flow — Master DB Multi-Tenant — Self-Test")
    print("=" * 60)

    # 1. Initialisation des structures
    print("\n[1] Initialisation des onglets maîtres...")
    result = initialize_master_structures()
    print("   →", result)

    # 2. Lecture config d'un snack
    TEST_SNACK_ID = "SNACK_TEST_01"
    print(f"\n[2] Lecture config pour '{TEST_SNACK_ID}'...")
    try:
        config = get_snack_config(TEST_SNACK_ID)
        print("   →", config)
    except KeyError as e:
        print(f"   ⚠️  {e}")

    # 3. Log d'une commande de test
    print(f"\n[3] Log d'une commande de test...")
    log_result = log_order(
        snack_id=TEST_SNACK_ID,
        customer_phone="+33785557054",
        order_details="1x Kebab, 1x Fanta",
        status="Lien envoyé",
    )
    print("   →", log_result)

    # 4. Vérification fidélité
    print(f"\n[4] Vérification fidélité...")
    loyalty = check_customer_loyalty(TEST_SNACK_ID, "+33785557054")
    print(f"   → Statut : {loyalty}")

    print("\n" + "=" * 60)
    print("   ✅ Self-Test terminé")
    print("=" * 60)
