"""
setup_demo_metz.py — Insertion du snack démo K-REVIEW (Metz)
=============================================================
Insère ou met à jour le restaurant K-REVIEW dans la table Supabase 'snacks'.
Utilise upsert sur whatsapp_phone_number_id pour être idempotent (safe à relancer).

Usage :
    python setup_demo_metz.py
"""

import json
import sys
import os

# Résolution du chemin racine pour les imports layer3_tools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from layer3_tools.supabase_tool import SupabaseClient, TABLE_SNACKS

# ─── Données du restaurant ────────────────────────────────────────────────────

RESTAURANT_NAME          = "K-REVIEW"
WHATSAPP_PHONE_NUMBER_ID = "33612345678"   # numéro fictif de démo

MENU_DATA = {
  "categories": [
    {
      "name": "Burgers",
      "items": [
        {
          "name": "Classic",
          "price": "6.50 EUR",
          "options": ["Sans oignons", "Extra Sauce", "Double Fromage"]
        },
        {
          "name": "Cheese",
          "price": "7.50 EUR",
          "options": ["Sans oignons", "Extra Sauce", "Double Fromage"]
        },
        {
          "name": "Bacon",
          "price": "8.50 EUR",
          "options": ["Sans oignons", "Extra Sauce", "Double Fromage"]
        },
        {
          "name": "Chicken",
          "price": "8.00 EUR",
          "options": ["Sans oignons", "Extra Sauce", "Double Fromage"]
        },
        {
          "name": "Double Cheese",
          "price": "9.50 EUR",
          "options": ["Sans oignons", "Extra Sauce", "Double Fromage"]
        }
      ]
    },
    {
      "name": "Sandwiches",
      "items": [
        {
          "name": "Kebab",
          "price": "7.00 EUR",
          "options": ["Salade", "Tomate", "Oignon", "Sauce Blanche", "Sauce Algérienne", "Harissa"]
        },
        {
          "name": "Kebab Fromage",
          "price": "8.00 EUR"
        },
        {
          "name": "Kebab Mixte",
          "price": "9.00 EUR"
        },
        {
          "name": "Kofte",
          "price": "8.00 EUR"
        }
      ]
    },
    {
      "name": "Menus",
      "items": [
        {
          "name": "Menu Burger Classic",
          "price": "10.50 EUR",
          "options": ["Frites", "Boisson 33cl"]
        },
        {
          "name": "Menu Kebab",
          "price": "11.00 EUR",
          "options": ["Frites", "Boisson 33cl"]
        },
        {
          "name": "Menu Mixte",
          "price": "13.00 EUR",
          "options": ["Frites", "Boisson 33cl"]
        }
      ]
    },
    {
      "name": "Boissons",
      "items": [
        {"name": "Eau 50cl",       "price": "1.50 EUR"},
        {"name": "Coca-Cola 33cl", "price": "2.00 EUR"},
        {"name": "Coca-Cola 50cl", "price": "3.00 EUR"},
        {"name": "Ayran",          "price": "2.00 EUR"},
        {"name": "Fanta 33cl",     "price": "2.00 EUR"}
      ]
    },
    {
      "name": "Desserts",
      "items": [
        {"name": "Baklava (x2)",    "price": "3.50 EUR"},
        {"name": "Tiramisu Maison", "price": "4.50 EUR"}
      ]
    }
  ]
}


# ─── Insertion / Mise à jour ──────────────────────────────────────────────────

def run():
    print("=" * 55)
    print("  SnackFlow — Setup Demo Metz — K-REVIEW")
    print("=" * 55)

    sb = SupabaseClient.instance()

    row = {
        "name":                     RESTAURANT_NAME,
        "whatsapp_phone_number_id": WHATSAPP_PHONE_NUMBER_ID,
        "is_active":                True,
        "menu_data":                MENU_DATA,
    }

    print(f"\n[1] Upsert '{RESTAURANT_NAME}' (phone_id={WHATSAPP_PHONE_NUMBER_ID})...")

    response = (
        sb.table(TABLE_SNACKS)
        .upsert(row, on_conflict="whatsapp_phone_number_id")
        .execute()
    )

    if not response.data:
        print("❌ Upsert échoué — aucune donnée retournée.")
        sys.exit(1)

    result = response.data[0]
    snack_uuid = result.get("id", "?")

    print(f"✅ Snack inséré/mis à jour avec succès !")
    print(f"\n{'─'*55}")
    print(f"  Nom          : {result.get('name')}")
    print(f"  UUID         : {snack_uuid}")
    print(f"  Phone ID     : {result.get('whatsapp_phone_number_id')}")
    print(f"  is_active    : {result.get('is_active')}")

    # Comptage des articles du menu
    categories = MENU_DATA.get("categories", [])
    total_items = sum(len(cat.get("items", [])) for cat in categories)
    print(f"  menu_data    : {len(categories)} catégories, {total_items} articles")
    print(f"{'─'*55}")

    print(f"\n[2] Vérification en lecture...")
    verify = (
        sb.table(TABLE_SNACKS)
        .select("id, name, whatsapp_phone_number_id, is_active, menu_data")
        .eq("id", snack_uuid)
        .single()
        .execute()
    )
    if verify.data and verify.data.get("menu_data"):
        cats_in_db = verify.data["menu_data"].get("categories", [])
        print(f"✅ Lecture OK — {len(cats_in_db)} catégories présentes en base.")
    else:
        print("⚠️  Lecture OK mais menu_data vide ou absent.")

    print(f"\n✅ K-REVIEW prêt sur SnackFlow !")
    print(f"   DEFAULT_SNACK_ID à mettre dans .env : {snack_uuid}")
    print("=" * 55)


if __name__ == "__main__":
    run()
