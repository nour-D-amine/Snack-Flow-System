"""
Layer 3 — Tools : Restaurant Registry (Snack-Flow v2.0 Full-WhatsApp)
=====================================================================
⚡ ARCHITECTURE MULTI-TENANT — SOURCE DE VÉRITÉ UNIQUE : SUPABASE

Ce module est un ADAPTATEUR qui délègue entièrement à supabase_tool.py.
La table `snacks` (Supabase/PostgreSQL) est la seule source de vérité.

Schéma de la table snacks :
  id (UUID) | name (TEXT) | phone_number_id (TEXT, unique) |
  menu_url (TEXT) | loyalty_threshold (INT) | is_active (BOOL)

Règles :
  - get_by_id(snack_id)         : lecture par UUID depuis snacks (Supabase)
  - get_by_phone_id(phone_id)   : authentification tenant par phone_number_id
  - list_all_restaurants()      : lecture complète de la table snacks
  - register_restaurant(...)    : upsert dans la table snacks
  - deactivate_restaurant(...)  : soft-delete (is_active = False)
  - Aucune donnée stockée localement — zéro GSheets, zéro fichier plat
"""

import os
import sys
import logging
from typing import Optional

from dotenv import load_dotenv

# Accès au root du projet pour les imports Layer 3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from layer3_tools.supabase_tool import (
    SupabaseClient,
    get_snack_config,
    get_snack_by_phone_id,
    list_all_snacks,
    upsert_snack,
    TABLE_SNACKS,
)

load_dotenv()

logger = logging.getLogger("snack_flow.registry")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s | restaurant_registry | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)


# =============================================================================
# API Publique — Lecture (délègue à supabase_tool)
# =============================================================================

def get_by_id(snack_id: str) -> Optional[dict]:
    """
    Retrouve un restaurant par son UUID Supabase (ou par name en fallback).
    Source de vérité : table snacks (Supabase).

    :param snack_id: UUID du restaurant (ex: "a1b2c3d4-...") ou name.
    :return: Dictionnaire de configuration enrichi, ou None si introuvable.
    """
    try:
        config = get_snack_config(snack_id)
        logger.info("✅ [Registry] Config chargée pour '%s' : %s", snack_id, config.get("name", "?"))
        return config
    except KeyError:
        logger.warning("⚠️  [Registry] snack_id '%s' introuvable dans Supabase.", snack_id)
        return None
    except Exception as e:
        logger.error("❌ [Registry] Erreur get_by_id(%s) : %s", snack_id, e)
        return None


def get_by_phone_id(phone_number_id: str) -> Optional[dict]:
    """
    Authentifie un tenant via son phone_number_id Meta WhatsApp.
    Source de vérité : colonne `whatsapp_phone_number_id` de la table snacks.

    :param phone_number_id: Valeur de metadata.phone_number_id reçue de Meta.
    :return: Enregistrement snack complet ou None si introuvable/inactif.
    """
    return get_snack_by_phone_id(phone_number_id)


def list_all_restaurants() -> list:
    """
    Retourne la liste de tous les restaurants actifs depuis la table snacks.

    :return: Liste de dictionnaires config (un par restaurant).
    """
    restaurants = list_all_snacks()
    if restaurants:
        logger.info("✅ [Registry] %d restaurant(s) chargé(s) depuis Supabase.", len(restaurants))
    else:
        logger.warning("⚠️  [Registry] Aucun restaurant trouvé dans Supabase.")
    return restaurants


# =============================================================================
# API Publique — Écriture (enregistrement d'un nouveau restaurant)
# =============================================================================

def register_restaurant(
    name: str,
    phone_number_id: str,
    menu_url: str = "",
    loyalty_threshold: int = 5,
    is_active: bool = True,
) -> dict:
    """
    Enregistre ou met à jour un restaurant dans la table snacks de Supabase.

    L'identifiant unique (clé d'upsert) est `phone_number_id` (Meta Phone Number ID).
    Un UUID `id` est automatiquement généré par Supabase à la création.

    :param name:              Nom du restaurant (ex: "Le Snack du Coin").
    :param phone_number_id:   Phone Number ID Meta WhatsApp Business (unique par tenant).
    :param menu_url:          URL du menu interactif (optionnel).
    :param loyalty_threshold: Nb de commandes pour déclencher la fidélité (défaut: 5).
    :param is_active:         Actif/inactif (défaut: True).
    :return: {'status': 'created'|'updated'|'error', 'snack': ...}
    """
    try:
        if not name.strip():
            return {"status": "error", "message": "Le paramètre 'name' est obligatoire."}
        if not phone_number_id.strip():
            return {"status": "error", "message": "Le paramètre 'phone_number_id' est obligatoire."}

        if not menu_url:
            slug = name.lower().replace(" ", "-").replace("'", "")
            menu_url = f"https://le-menu.app/{slug}"

        sb = SupabaseClient.instance()

        # Vérifie si le restaurant existe déjà (par phone_number_id)
        existing_resp = (
            sb.table(TABLE_SNACKS)
            .select("id, name")
            .eq("whatsapp_phone_number_id", phone_number_id.strip())
            .execute()
        )
        is_new = not bool(existing_resp.data)

        # Upsert via supabase_tool (clé : whatsapp_phone_number_id)
        result = upsert_snack(
            name=name,
            whatsapp_phone_number_id=phone_number_id,
            menu_url=menu_url,
            loyalty_threshold=loyalty_threshold,
            is_active=is_active,
        )

        if "error" in result:
            return {"status": "error", "message": result["error"]}

        action = "created" if is_new else "updated"
        logger.info(
            "✅ [Registry] Restaurant '%s' %s | phone_number_id=%s",
            name, action, phone_number_id,
        )
        return {"status": action, "snack": result}

    except Exception as e:
        logger.error("❌ [Registry] Erreur register_restaurant('%s') : %s", name, e)
        return {"status": "error", "message": str(e)}


def deactivate_restaurant(phone_number_id: str) -> bool:
    """
    Désactive un restaurant (soft-delete : is_active = False).
    La ligne est conservée en base pour l'historique des commandes.

    :param phone_number_id: Phone Number ID Meta du restaurant à désactiver.
    :return: True si trouvé et désactivé, False sinon.
    """
    try:
        sb = SupabaseClient.instance()
        response = (
            sb.table(TABLE_SNACKS)
            .update({"is_active": False})
            .eq("whatsapp_phone_number_id", phone_number_id.strip())
            .execute()
        )
        if response.data:
            name = response.data[0].get("name", phone_number_id)
            logger.info("✅ [Registry] Restaurant '%s' désactivé.", name)
            return True

        logger.warning("⚠️  [Registry] phone_number_id '%s' non trouvé dans Supabase.", phone_number_id)
        return False

    except Exception as e:
        logger.error("❌ [Registry] Erreur deactivate_restaurant(%s) : %s", phone_number_id, e)
        return False


# =============================================================================
# Test standalone
# =============================================================================

if __name__ == "__main__":
    print("━" * 55)
    print("  🏪 Restaurant Registry v2.0 — Supabase Only")
    print("━" * 55)

    print("\n📋 Liste de tous les restaurants (source : table snacks) :")
    restos = list_all_restaurants()
    if restos:
        for r in restos:
            print(
                f"  • [{r.get('id', '?')[:8]}...] {r.get('name', '?')} "
                f"| phone_id={r.get('whatsapp_phone_number_id', '—')} "
                f"| Actif={r.get('is_active', '?')}"
            )
    else:
        print("  Aucun restaurant enregistré dans Supabase.")

    print("\n━" * 55)
