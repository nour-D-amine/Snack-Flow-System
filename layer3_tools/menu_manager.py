"""
Layer 3 — Tools : Menu Manager (SnackFlow v3.1)
================================================
Module dédié à la construction et l'envoi du menu interactif WhatsApp.

Fonctions publiques :
  - build_menu_sections(menu_data) → list    Construit les sections List Message
  - send_interactive_menu(config, phone)     Envoie le menu interactif au client
  - send_main_menu                           Alias backward-compat
"""

from __future__ import annotations

import logging

logger = logging.getLogger("snack_flow.menu_manager")


def build_menu_sections(menu_data) -> list:
    """
    Construit les sections WhatsApp List Message depuis menu_data (JSONB Supabase).

    Formats acceptés :
      1. {"categories": [{"name": "Burgers", "items": [{"id":…,"name":…,"price":…}]}]}
      2. [{"id":…, "name":…, "price":…, "category": "Burgers"}]
      3. {"Burgers": [{"id":…, "name":…, "price":…}], …}

    Retourne une liste de sections compatibles avec send_list_menu().
    """
    if not menu_data:
        return []

    sections = []

    # Format 1 — dict avec clé "categories"
    if isinstance(menu_data, dict) and "categories" in menu_data:
        for cat in menu_data["categories"]:
            rows = []
            for item in cat.get("items", []):
                item_id    = str(item.get("id") or item.get("name", "?"))
                item_name  = str(item.get("name", "?"))
                item_price = item.get("price")
                desc = f"{item_price:.2f}€" if isinstance(item_price, (int, float)) else str(item_price or "")
                rows.append({"id": item_id, "title": item_name, "description": desc})
            if rows:
                sections.append({"title": cat.get("name", "Menu"), "rows": rows})

    # Format 2 — liste plate
    elif isinstance(menu_data, list):
        by_cat: dict = {}
        for item in menu_data:
            cat_name  = str(item.get("category", "Menu"))
            item_id   = str(item.get("id") or item.get("name", "?"))
            item_name = str(item.get("name", "?"))
            price     = item.get("price")
            desc = f"{price:.2f}€" if isinstance(price, (int, float)) else str(price or "")
            by_cat.setdefault(cat_name, []).append({"id": item_id, "title": item_name, "description": desc})
        for cat_name, rows in by_cat.items():
            sections.append({"title": cat_name, "rows": rows})

    # Format 3 — dict de catégories
    elif isinstance(menu_data, dict):
        for cat_name, items in menu_data.items():
            if not isinstance(items, list):
                continue
            rows = []
            for item in items:
                item_id   = str(item.get("id") or item.get("name", "?"))
                item_name = str(item.get("name", "?"))
                price     = item.get("price")
                desc = f"{price:.2f}€" if isinstance(price, (int, float)) else str(price or "")
                rows.append({"id": item_id, "title": item_name, "description": desc})
            if rows:
                sections.append({"title": cat_name, "rows": rows})

    logger.debug("build_menu_sections → %d section(s)", len(sections))
    return sections


def send_interactive_menu(config: dict, phone: str) -> None:
    """
    Envoie le menu interactif WhatsApp (List Message) au client.
    Construit dynamiquement depuis menu_data Supabase.
    Utilise logo_url du snack comme header image si disponible.
    Fallback texte si menu_data absent ou vide.

    :param config: Dict issu de supabase_tool.get_snack_config().
    :param phone:  Numéro du client au format E.164.
    """
    from layer3_tools.whatsapp_tool import send_list_menu, send_text_message

    nom_resto = config.get("nom_resto") or config.get("name", "Notre Snack")
    menu_data = config.get("menu_data")
    sections  = build_menu_sections(menu_data)

    if not sections:
        logger.info("send_interactive_menu : menu_data vide pour '%s' → fallback texte", nom_resto)
        send_text_message(
            config, phone,
            f"👋 Bienvenue chez *{nom_resto}* !\n\n"
            "Notre menu interactif n'est pas encore configuré.\n"
            "Écrivez votre commande directement et nous la traiterons rapidement. 🙏",
        )
        return

    logo_url = str(config.get("logo_url", "") or "").strip()

    send_list_menu(
        config=config,
        customer_phone=phone,
        sections=sections,
        logo_url=logo_url,
        header_text="" if logo_url else f"🍔 {nom_resto}"[:60],
        body_text=(
            "Bonjour ! 👋 Bienvenue chez *" + nom_resto + "*.\n"
            "Sélectionnez un article pour l'ajouter à votre panier."
        ),
        button_text="Voir le menu",
        footer_text="SnackFlow • Commande rapide",
    )
    logger.info("send_interactive_menu → List Message envoyé à %s (%d sections)", phone, len(sections))


# Alias backward-compat — l'ancien nom est conservé pour ne pas casser les imports existants
send_main_menu = send_interactive_menu
