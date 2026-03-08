"""
Layer 1 — SOPs : Remarketing (Snack-Flow Multi-Tenant)
=======================================================
Fondations du moteur de remarketing.
Identifie les clients inactifs d'un restaurant et déclenche
des campagnes de relance via WhatsApp Business API.

Ce module est la base de Phase 4 (enrichissement : fréquence,
préférences, saisonnalité).
"""

import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from layer3_tools.crm_tool import get_remarketing_targets, get_restaurant_stats
from layer3_tools.whatsapp_tool import send_text_message
from layer3_tools.gsheets_tool import get_snack_config
from layer3_tools.restaurant_registry import get_by_id, list_all_restaurants

load_dotenv()


# =============================================================================
# SOP-R01 : Rapport Remarketing par Restaurant
# =============================================================================

def generate_remarketing_report(restaurant_id: str, inactive_days: int = 30) -> dict:
    """
    Génère un rapport de performance et identifie les clients éligibles
    à une campagne de re-engagement pour un restaurant donné.

    :param restaurant_id:  ID du restaurant.
    :param inactive_days:  Seuil d'inactivité (en jours) pour être ciblé.
    :return:               Rapport dict avec stats + liste cibles.
    """
    print(f"\n📊 [REMARKETING] Rapport pour {restaurant_id} (inactifs depuis {inactive_days}j)")

    restaurant = get_by_id(restaurant_id)
    resto_name = restaurant["nom_resto"] if restaurant else restaurant_id

    stats = get_restaurant_stats(restaurant_id)
    targets = get_remarketing_targets(restaurant_id, inactive_days=inactive_days)

    report = {
        "restaurant_id":   restaurant_id,
        "restaurant_name": resto_name,
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "inactive_days_threshold": inactive_days,
        "stats": {
            "total_clients":      stats.get("total_clients", 0),
            "total_orders":       stats.get("total_orders", 0),
            "active_this_month":  stats.get("active_this_month", 0),
        },
        "remarketing_targets_count": len(targets),
        "targets": [
            {
                "phone":         t["phone_e164"],
                "last_contact":  t["last_contact"],
                "total_orders":  t["total_orders"],
            }
            for t in targets
        ]
    }

    # Affichage
    print(f"   🏪 {resto_name}")
    print(f"   👥 Total clients : {report['stats']['total_clients']}")
    print(f"   🛒 Total commandes : {report['stats']['total_orders']}")
    print(f"   📅 Actifs ce mois : {report['stats']['active_this_month']}")
    print(f"   🎯 Ciblés pour relance : {len(targets)} client(s)")

    return report


# =============================================================================
# SOP-R02 : Campagne SMS de Relance
# =============================================================================

def send_remarketing_campaign(
    restaurant_id: str,
    message_template: str = None,
    inactive_days: int = 30,
    dry_run: bool = False
) -> dict:
    """
    Envoie une campagne SMS de relance aux clients inactifs d'un restaurant.
    Self-Healing : si un SMS échoue, log l'erreur et continue.

    :param restaurant_id:     ID du restaurant.
    :param message_template:  Template du message (supporte {name} et {menu_url}).
                              Si None, utilise le template par défaut.
    :param inactive_days:     Seuil d'inactivité pour cibler les clients.
    :param dry_run:           Si True, simule sans envoyer de SMS.
    :return:                  Résumé de la campagne (envoyés / échoués).
    """
    restaurant = get_by_id(restaurant_id)
    if not restaurant:
        print(f"❌ Restaurant {restaurant_id} introuvable.")
        return {"status": "error", "message": "Restaurant introuvable"}

    resto_name = restaurant.get("nom_resto", "le restaurant")
    menu_url   = restaurant.get("menu_url", "https://snack-flow.com/menu")

    # Template par défaut
    if not message_template:
        message_template = (
            f"🍔 {resto_name} pense à vous !\n"
            f"Cela fait un moment... Notre menu vous attend ici :\n"
            f"{menu_url}\n\n"
            f"— L'équipe {resto_name}"
        )

    targets = get_remarketing_targets(restaurant_id, inactive_days=inactive_days)
    if not targets:
        print(f"ℹ️  Aucun client à relancer pour {restaurant_id}.")
        return {"status": "no_targets", "sent": 0, "failed": 0}

    print(f"\n🚀 [REMARKETING] Campagne démarrée pour '{resto_name}' | {len(targets)} client(s)")
    if dry_run:
        print("   ⚠️  MODE DRY-RUN — Aucun message ne sera envoyé\n")

    # Chargement de la config WhatsApp du restaurant
    try:
        config = get_snack_config(restaurant_id)
    except KeyError:
        print(f"❌ Config WhatsApp introuvable pour {restaurant_id} — campagne annulée.")
        return {"status": "error", "message": "config snack introuvable"}

    sent_count   = 0
    failed_count = 0
    results      = []

    for target in targets:
        phone = target["phone_e164"]
        try:
            if dry_run:
                print(f"   [DRY-RUN] → Message simulé pour {phone}")
                results.append({"phone": phone, "status": "dry_run"})
                sent_count += 1
            else:
                result = send_text_message(config, phone, message_template)
                if "error" not in result:
                    print(f"   ✅ WhatsApp envoyé à {phone}")
                    results.append({"phone": phone, "status": "sent"})
                    sent_count += 1
                else:
                    err_msg = result.get("error", "Erreur API")
                    print(f"   ❌ Échec WhatsApp pour {phone} : {err_msg}")
                    results.append({"phone": phone, "status": "failed", "error": err_msg})
                    failed_count += 1
        except Exception as e:
            print(f"   ❌ Erreur critique pour {phone} : {e}")
            results.append({"phone": phone, "status": "error", "error": str(e)})
            failed_count += 1

    summary = {
        "status":        "completed",
        "restaurant_id": restaurant_id,
        "campaign_date": datetime.now(timezone.utc).isoformat(),
        "total_targeted": len(targets),
        "sent":          sent_count,
        "failed":        failed_count,
        "dry_run":       dry_run,
        "results":       results
    }

    print(f"\n✅ [REMARKETING] Campagne terminée | Envoyés: {sent_count} | Échecs: {failed_count}")
    return summary


# =============================================================================
# SOP-R03 : Campagne globale (tous les restaurants)
# =============================================================================

def run_global_remarketing_campaign(inactive_days: int = 30, dry_run: bool = True) -> list:
    """
    Lance une campagne de relance pour TOUS les restaurants actifs.
    Par défaut en dry_run pour éviter les envois accidentels.

    :return: Liste des résumés de campagne par restaurant.
    """
    print(f"\n🌍 [REMARKETING GLOBAL] Démarrage | inactive_days={inactive_days} | dry_run={dry_run}")
    restaurants = list_all_restaurants()

    if not restaurants:
        print("ℹ️  Aucun restaurant actif dans le registre.")
        return []

    all_results = []
    for resto in restaurants:
        result = send_remarketing_campaign(
            restaurant_id=resto.get("snack_id", ""),
            inactive_days=inactive_days,
            dry_run=dry_run
        )
        all_results.append(result)

    print(f"\n✅ [REMARKETING GLOBAL] {len(all_results)} restaurant(s) traité(s).")
    return all_results


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Snack-Flow — Moteur de Remarketing")
    parser.add_argument("--restaurant-id", help="ID du restaurant ciblé (ou 'all' pour tous)")
    parser.add_argument("--inactive-days", type=int, default=30, help="Seuil d'inactivité (défaut: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans envoi SMS")
    parser.add_argument("--report-only", action="store_true", help="Affiche uniquement le rapport")
    args = parser.parse_args()

    if not args.restaurant_id:
        print("Usage : python remarketing_sop.py --restaurant-id ID [--dry-run] [--report-only]")
        print("        python remarketing_sop.py --restaurant-id all --dry-run")
        sys.exit(0)

    if args.restaurant_id == "all":
        run_global_remarketing_campaign(args.inactive_days, dry_run=args.dry_run)
    elif args.report_only:
        generate_remarketing_report(args.restaurant_id, args.inactive_days)
    else:
        send_remarketing_campaign(
            args.restaurant_id,
            inactive_days=args.inactive_days,
            dry_run=args.dry_run
        )
