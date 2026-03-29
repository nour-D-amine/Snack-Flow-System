import os
from layer3_tools.supabase_tool import get_client, TABLE_SNACKS

def populate_snack():
    print("🚀 Démarrage du script de reset K-REVIEW...")
    client = get_client()

    print("Suppression des anciens K-REVIEW ou numéros '33612345678'...")
    try:
        client.table(TABLE_SNACKS).delete().eq("whatsapp_phone_number_id", "33612345678").execute()
    except Exception as e:
        pass
    
    try:
        client.table(TABLE_SNACKS).delete().eq("name", "K-REVIEW").execute()
    except Exception as e:
        pass

    print("Insertion du nouveau snack K-REVIEW avec menu dynamique...")
    menu_data = {
      "categories": [
        {
          "name": "Menus",
          "items": [
            { "name": "Menu Burger Classic", "price": "10.50 EUR", "options": ["Frites", "Boisson 33cl"] },
            { "name": "Menu Kebab", "price": "11.00 EUR", "options": ["Frites", "Boisson 33cl"] }
          ]
        },
        {
          "name": "Burgers Seuls",
          "items": [
            { "name": "Burger Classic", "price": "6.50 EUR", "options": ["Sans oignons", "Double Fromage"] },
            { "name": "Double Cheese", "price": "9.50 EUR", "options": ["Double Fromage"] }
          ]
        },
        {
          "name": "Boissons",
          "items": [
            { "name": "Coca-Cola 33cl", "price": "2.00 EUR" },
            { "name": "Ayran", "price": "2.00 EUR" },
            { "name": "Eau 50cl", "price": "1.50 EUR" }
          ]
        },
        {
          "name": "Desserts",
          "items": [
            { "name": "Baklava (x2)", "price": "3.50 EUR" },
            { "name": "Tiramisu Maison", "price": "4.50 EUR" }
          ]
        }
      ]
    }

    payload = {
        "name": "K-REVIEW",
        "whatsapp_phone_number_id": "33612345678",
        "is_active": True,
        "menu_data": menu_data
    }

    try:
        res = client.table(TABLE_SNACKS).insert(payload).execute()
        print("✅ Snack inséré avec succès :", res.data[0]['id'])
    except Exception as e:
        print("❌ Erreur lors de l'insertion :", e)

if __name__ == "__main__":
    populate_snack()
