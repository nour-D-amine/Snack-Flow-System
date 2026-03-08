"""
Layer 3 — Tools : Restaurant Registry (Snack-Flow Multi-Tenant)
================================================================
⚡ ARCHITECTURE MULTI-TENANT — SOURCE DE VÉRITÉ UNIQUE

Ce module est un ADAPTATEUR qui délègue entièrement à gsheets_tool.py.
Le Google Sheet Master (onglet 'RESTOS') est la seule source de vérité.

Schéma de l'onglet RESTOS (géré par gsheets_tool.initialize_master_structures) :
  snack_id | nom_resto | whatsapp_phone_id | whatsapp_token | menu_url | loyalty_threshold | resto_phone

Règles :
  - get_snack_config(snack_id)  : lecture directe dans RESTOS via GSheets (batch optimisé)
  - Aucune donnée n'est stockée localement dans ce module
  - Si un snack_id est inconnu → KeyError explicite (Self-Healing)
  - Twilio : supprimé définitivement
"""

import os
import sys
from typing import Optional
from datetime import datetime, timezone

import gspread
from dotenv import load_dotenv

# Accès au root du projet pour les imports Layer 3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from layer3_tools.gsheets_tool import get_snack_config, initialize_master_structures

load_dotenv()

SERVICE_ACCOUNT_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "service_account.json"
)
MASTER_SHEET_ID = os.getenv("GOOGLE_SHEET_MASTER_ID") or os.getenv("GOOGLE_SHEET_ID")

# Colonnes de l'onglet RESTOS (source de vérité)
RESTOS_HEADERS = [
    "snack_id",
    "nom_resto",
    "whatsapp_phone_id",
    "whatsapp_token",
    "menu_url",
    "loyalty_threshold",
    "resto_phone",
]


# =============================================================================
# API Publique — Lecture (délègue à gsheets_tool)
# =============================================================================

def get_by_id(snack_id: str) -> Optional[dict]:
    """
    Retrouve un restaurant par son snack_id.
    Source de vérité : onglet RESTOS du Google Sheet Master.

    :param snack_id: Identifiant unique du restaurant (ex: SNACK_PARIS_01).
    :return: Dictionnaire de configuration ou None si introuvable.
    """
    try:
        config = get_snack_config(snack_id)
        print(f"✅ [Registry] Config chargée pour '{snack_id}' : {config.get('nom_resto', '?')}")
        return config
    except KeyError:
        print(f"⚠️  [Registry] snack_id '{snack_id}' introuvable dans RESTOS.")
        return None
    except Exception as e:
        print(f"❌ [Registry] Erreur get_by_id({snack_id}) : {e}")
        return None


def list_all_restaurants() -> list:
    """
    Retourne la liste de tous les restaurants actifs depuis RESTOS.

    :return: Liste de dictionnaires config (un par restaurant).
    """
    try:
        if not MASTER_SHEET_ID:
            raise ValueError("GOOGLE_SHEET_MASTER_ID manquant dans .env")

        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(MASTER_SHEET_ID)

        try:
            ws = sh.worksheet("RESTOS")
        except gspread.exceptions.WorksheetNotFound:
            print("⚠️  Onglet RESTOS introuvable — exécutez initialize_master_structures()")
            return []

        rows = ws.get_all_values()
        if len(rows) <= 1:
            return []

        headers = rows[0]
        restaurants = []
        for row in rows[1:]:
            if len(row) < 2 or not row[0].strip():
                continue  # Ignore les lignes vides
            resto = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
            restaurants.append(resto)

        print(f"✅ [Registry] {len(restaurants)} restaurant(s) chargé(s) depuis RESTOS.")
        return restaurants

    except Exception as e:
        print(f"❌ [Registry] Erreur list_all_restaurants : {e}")
        return []


# =============================================================================
# API Publique — Écriture (enregistrement d'un nouveau restaurant)
# =============================================================================

def register_restaurant(
    snack_id: str,
    nom_resto: str,
    whatsapp_phone_id: str,
    whatsapp_token: str,
    menu_url: str = "",
    loyalty_threshold: int = 5,
    resto_phone: str = "",
) -> dict:
    """
    Enregistre un nouveau restaurant dans l'onglet RESTOS du Google Sheet Master.

    :param snack_id: Identifiant unique (ex: SNACK_PARIS_01). Doit être unique.
    :param nom_resto: Nom du restaurant.
    :param whatsapp_phone_id: Phone Number ID Meta WhatsApp Business.
    :param whatsapp_token: Token d'accès Meta Graph API (spécifique au tenant).
    :param menu_url: URL du menu interactif.
    :param loyalty_threshold: Nombre de commandes pour déclencher la fidélité.
    :param resto_phone: Numéro de téléphone public du restaurant (E.164).
    :return: {'status': 'created'|'already_exists'|'error', 'snack_id': ...}
    """
    try:
        # Vérifie que le snack_id n'existe pas déjà
        existing = get_by_id(snack_id)
        if existing:
            print(f"⚠️  [Registry] snack_id '{snack_id}' déjà enregistré : {existing.get('nom_resto')}")
            return {"status": "already_exists", "snack_id": snack_id, "restaurant": existing}

        if not MASTER_SHEET_ID:
            raise ValueError("GOOGLE_SHEET_MASTER_ID manquant dans .env")

        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(MASTER_SHEET_ID)

        try:
            ws = sh.worksheet("RESTOS")
        except gspread.exceptions.WorksheetNotFound:
            initialize_master_structures()
            ws = sh.worksheet("RESTOS")

        if not menu_url:
            slug = nom_resto.lower().replace(" ", "-").replace("'", "")
            menu_url = f"https://snack-flow.com/menu/{slug}"

        new_row = [
            snack_id,
            nom_resto,
            whatsapp_phone_id,
            whatsapp_token,
            menu_url,
            str(loyalty_threshold),
            resto_phone,
        ]

        ws.append_row(new_row, value_input_option="USER_ENTERED")
        print(f"✅ [Registry] Restaurant '{nom_resto}' enregistré (snack_id: {snack_id})")

        return {
            "status": "created",
            "snack_id": snack_id,
            "restaurant": {h: new_row[i] for i, h in enumerate(RESTOS_HEADERS)},
        }

    except Exception as e:
        print(f"❌ [Registry] Erreur register_restaurant : {e}")
        return {"status": "error", "message": str(e)}


def deactivate_restaurant(snack_id: str) -> bool:
    """
    Supprime la ligne correspondant à snack_id dans RESTOS.
    (Soft-delete non implémenté dans ce schéma — suppression directe.)

    :return: True si trouvé et supprimé, False sinon.
    """
    try:
        if not MASTER_SHEET_ID:
            raise ValueError("GOOGLE_SHEET_MASTER_ID manquant dans .env")

        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        sh = gc.open_by_key(MASTER_SHEET_ID)
        ws = sh.worksheet("RESTOS")

        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if row and row[0] == snack_id:
                ws.delete_rows(idx)
                print(f"✅ [Registry] Restaurant '{snack_id}' supprimé de RESTOS.")
                return True

        print(f"⚠️  [Registry] snack_id '{snack_id}' non trouvé dans RESTOS.")
        return False

    except Exception as e:
        print(f"❌ [Registry] Erreur deactivate_restaurant : {e}")
        return False


# =============================================================================
# Test standalone
# =============================================================================

if __name__ == "__main__":
    print("━" * 55)
    print("  🏪 Restaurant Registry — Test Multi-Tenant")
    print("━" * 55)

    print("\n📋 Liste de tous les restaurants (source : onglet RESTOS) :")
    restos = list_all_restaurants()
    if restos:
        for r in restos:
            print(
                f"  • [{r.get('snack_id','?')}] {r.get('nom_resto','?')} "
                f"| Menu : {r.get('menu_url','—')} "
                f"| Seuil fidélité : {r.get('loyalty_threshold','?')}"
            )
    else:
        print("  Aucun restaurant enregistré dans RESTOS.")

    print("\n━" * 55)
