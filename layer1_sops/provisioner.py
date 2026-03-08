"""
Layer 1 — SOPs : Provisioner Restaurant (Snack-Flow Multi-Tenant)
=================================================================
Script d'onboarding CLI : crée l'environnement complet d'un restaurant
en saisissant uniquement 2 informations essentielles :
  - Numéro de téléphone du restaurant (public, E.164)
  - Numéro WhatsApp Business (sans '+')

Ce que le provisioner crée automatiquement :
  ✅ Un restaurant_id unique
  ✅ Une URL de menu dédiée (slug généré depuis le nom)
  ✅ Un Google Sheet de logs dédié (copie du template)
  ✅ L'enregistrement dans le Sheet Master (onglet RESTOS)

Usage :
  python provisioner.py
  python provisioner.py --dry-run   (simulation sans écriture)
  python provisioner.py --list      (liste tous les restaurants)
"""

import os
import sys
import argparse

# Chemin racine du projet
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import gspread
from dotenv import load_dotenv
from layer3_tools.phone_tool import safe_normalize, normalize_e164
from layer3_tools.restaurant_registry import (
    register_restaurant,
    list_all_restaurants,
    update_sheet_id
)
from layer3_tools.crm_tool import initialize_db

load_dotenv()

SERVICE_ACCOUNT_FILE = os.path.join(PROJECT_ROOT, "service_account.json")
SHEET_TEMPLATE_ID = os.getenv("GOOGLE_SHEET_TEMPLATE_ID")  # ID du Sheet template à dupliquer


# =============================================================================
# ÉTAPE 1 — Collecte des informations
# =============================================================================

def collect_restaurant_info(dry_run: bool = False) -> dict:
    """
    Interaction CLI pour collecter les informations du restaurant.
    Valide les numéros au format E.164.

    :return: Dictionnaire avec toutes les infos validées.
    """
    print("\n" + "═" * 60)
    print("  🍔  SNACK-FLOW — Onboarding Nouveau Restaurant")
    print("═" * 60)

    if dry_run:
        print("  ⚠️  MODE SIMULATION (--dry-run) : aucune écriture\n")

    # Nom du restaurant
    name = input("\n1️⃣  Nom du restaurant : ").strip()
    if not name:
        raise ValueError("Le nom du restaurant est requis.")

    # Numéro de téléphone public
    phone_raw = input("2️⃣  Numéro de téléphone public (ex: 0612345678 ou +33612345678) : ").strip()
    phone_result = normalize_e164(phone_raw)
    if phone_result["status"] != "ok":
        raise ValueError(f"Numéro de téléphone invalide : {phone_result['message']}")
    phone_e164 = phone_result["e164"]
    print(f"   ✅ Normalisé : {phone_e164}")

    # Numéro WhatsApp Business
    whatsapp_raw = input("3️⃣  Numéro WhatsApp Business (ex: 0612345678 ou +33612345678) : ").strip()
    whatsapp_result = normalize_e164(whatsapp_raw)
    if whatsapp_result["status"] != "ok":
        raise ValueError(f"Numéro WhatsApp invalide : {whatsapp_result['message']}")
    # WhatsApp Meta API : sans le '+', juste les chiffres
    whatsapp_number = whatsapp_result["e164"].lstrip("+")
    print(f"   ✅ Normalisé : {whatsapp_number}")

    # URL menu (optionnelle)
    slug = name.lower().replace(" ", "-").replace("'", "").replace("é", "e").replace("è", "e").replace("ê", "e")
    default_menu_url = f"https://snack-flow.com/menu/{slug}"
    print(f"\n4️⃣  URL du menu interactif")
    print(f"   (Appuyez Entrée pour utiliser : {default_menu_url})")
    menu_url = input("   URL menu : ").strip() or default_menu_url

    return {
        "name": name,
        "phone_e164": phone_e164,
        "whatsapp_number": whatsapp_number,
        "menu_url": menu_url,
    }


# =============================================================================
# ÉTAPE 2 — Création du Google Sheet dédié
# =============================================================================

def create_dedicated_sheet(restaurant_name: str, dry_run: bool = False) -> str:
    """
    Crée un Google Sheet dédié pour le restaurant en dupliquant le template.
    Si aucun template n'est configuré, crée un Sheet vierge avec les bons entêtes.

    :return: L'ID du Google Sheet créé (ou "" en dry_run).
    """
    if dry_run:
        print("   [DRY-RUN] Création du Google Sheet simulée.")
        return "dry_run_sheet_id"

    try:
        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)

        if SHEET_TEMPLATE_ID:
            # Duplique le template existant
            sheet = gc.copy(
                file_id=SHEET_TEMPLATE_ID,
                title=f"Snack-Flow | {restaurant_name}",
                copy_permissions=True
            )
            print(f"   ✅ Sheet créé depuis template : {sheet.id}")
        else:
            # Crée un nouveau Sheet vierge
            sheet = gc.create(f"Snack-Flow | {restaurant_name}")
            # Initialise les entêtes
            ws = sheet.sheet1
            ws.append_row([
                "Date", "Heure", "Numéro Client (E.164)",
                "Choix IVR", "Statut SMS Client", "Statut Transfert/WhatsApp"
            ])
            print(f"   ✅ Nouveau Sheet créé (vierge) : {sheet.id}")

        return sheet.id

    except Exception as e:
        print(f"   ❌ Erreur création Sheet : {e}")
        return ""


# =============================================================================
# ÉTAPE 3 — Enregistrement dans le registre
# =============================================================================

def provision_restaurant(dry_run: bool = False):
    """
    Fonction principale d'onboarding : collecte, crée le Sheet, enregistre.
    """
    try:
        # Collecte des infos
        info = collect_restaurant_info(dry_run=dry_run)

        print("\n" + "─" * 60)
        print("🔄 Provisioning en cours...\n")

        # Création du Google Sheet dédié
        print("📊 Étape 1/3 : Création du Google Sheet dédié...")
        sheet_id = create_dedicated_sheet(info["name"], dry_run=dry_run)

        # Enregistrement dans le registre
        print("📋 Étape 2/3 : Enregistrement dans le registre...")
        if not dry_run:
            result = register_restaurant(
                name=info["name"],
                phone_e164=info["phone_e164"],
                whatsapp_number=info["whatsapp_number"],
                menu_url=info["menu_url"],
                google_sheet_id=sheet_id,
            )
            if result["status"] == "already_exists":
                print(f"   ⚠️  Restaurant déjà existant. Provisioning annulé.")
                return
            restaurant = result["restaurant"]
            restaurant_id = restaurant["restaurant_id"]
            print(f"   ✅ Restaurant enregistré (ID: {restaurant_id})")
        else:
            restaurant_id = "dry_run_id"
            print("   [DRY-RUN] Enregistrement simulé.")

        # Initialisation de la base CRM
        print("🗃️  Étape 3/3 : Initialisation du CRM...")
        if not dry_run:
            initialize_db()
        else:
            print("   [DRY-RUN] CRM SQLite non modifié.")

        # Résumé final
        _print_summary(info, restaurant_id, sheet_id)

    except ValueError as e:
        print(f"\n❌ Erreur de saisie : {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Provisioning annulé par l'utilisateur.")
        sys.exit(0)


# =============================================================================
# RAPPORT FINAL
# =============================================================================

def _print_summary(info: dict, restaurant_id: str, sheet_id: str):
    """Affiche le récapitulatif d'onboarding."""
    print("\n" + "═" * 60)
    print("  ✅  ONBOARDING TERMINÉ — Récapitulatif")
    print("═" * 60)
    print(f"  🏪 Restaurant      : {info['name']}")
    print(f"  🆔 ID              : {restaurant_id}")
    print(f"  📞 Tél public      : {info['phone_e164']}")
    print(f"  📱 WhatsApp        : +{info['whatsapp_number']}")
    print(f"  🔗 Menu URL        : {info['menu_url']}")
    print(f"  📊 Google Sheet    : {sheet_id or 'Non créé'}")
    print("─" * 60)
    print("\n  📌 VARIABLES .env À COMPLÉTER :")
    print(f"  RESTAURANT_WHATSAPP_NUMBER=\"{info['whatsapp_number']}\"")
    print(f"  RESTAURANT_PHONE_NUMBER=\"{info['phone_e164']}\"")
    print(f"  MENU_URL=\"{info['menu_url']}\"")
    print("═" * 60 + "\n")


# =============================================================================
# LISTE DES RESTAURANTS
# =============================================================================

def list_restaurants():
    """Affiche tous les restaurants actifs dans le registre."""
    print("\n📋 Restaurants actifs dans Snack-Flow :\n")
    restos = list_all_restaurants()
    if not restos:
        print("  Aucun restaurant enregistré.")
        return

    print(f"  {'ID':<15} {'Nom':<20} {'Téléphone':<18} {'WhatsApp':<20} {'Menu URL'}")
    print("  " + "─" * 90)
    for r in restos:
        print(f"  {r['restaurant_id']:<15} {r['name']:<20} {r['phone_e164']:<18} "
              f"+{r['whatsapp_number']:<19} {r.get('menu_url', '—')}")
    print()


# =============================================================================
# POINT D'ENTRÉE CLI
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Snack-Flow — Provisioner de restaurant"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule le provisioning sans écriture"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Liste tous les restaurants actifs"
    )
    args = parser.parse_args()

    if args.list:
        list_restaurants()
    else:
        provision_restaurant(dry_run=args.dry_run)
