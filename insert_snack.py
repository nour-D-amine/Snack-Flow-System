"""
Script d'initialisation Multi-Tenant : insère le premier snack en base.
Usage : python insert_snack.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from layer3_tools.supabase_tool import SupabaseClient, TABLE_SNACKS

SNACK_DATA = {
    "name": "Snack Test 01",
    "whatsapp_phone_number_id": "919410367932677",
    "is_active": True,
}


def main():
    print("🚀 Insertion du premier snack en base...")

    sb = SupabaseClient.instance()

    # Vérifie si un snack avec ce phone_number_id existe déjà
    existing = (
        sb.table(TABLE_SNACKS)
        .select("id, name")
        .eq("whatsapp_phone_number_id", SNACK_DATA["whatsapp_phone_number_id"])
        .execute()
    )

    if existing.data:
        row = existing.data[0]
        print(
            f"⚠️  Snack déjà existant → id={row['id']} | name={row['name']} "
            f"| phone_id={SNACK_DATA['whatsapp_phone_number_id']}"
        )
        print("   Aucune insertion effectuée (idempotent).")
        return

    response = sb.table(TABLE_SNACKS).insert(SNACK_DATA).execute()

    if response.data:
        row = response.data[0]
        print(f"✅ Snack inséré avec succès !")
        print(f"   id                      : {row.get('id')}")
        print(f"   name                    : {row.get('name')}")
        print(f"   whatsapp_phone_number_id: {row.get('whatsapp_phone_number_id')}")
        print(f"   is_active               : {row.get('is_active')}")
    else:
        print("❌ Insertion échouée — aucune donnée retournée.")
        sys.exit(1)


if __name__ == "__main__":
    main()
