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
            # Skip les clés internes (ex: _out_of_stock ajouté par sync_stock)
            if cat_name.startswith("_"):
                continue
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
            "Notre menu est en cours de configuration.\n"
            "Veuillez réessayer dans quelques instants. 🙏",
        )
        return

    logo_url = str(config.get("logo_url", "") or "").strip()

    result = send_list_menu(
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

    if result and "error" in result:
        logger.error("❌ Le menu interactif a été rejeté par Meta : %s. Passage au fallback texte.", result.get("error"))
        fallback_msg = (
            f"👋 Bienvenue chez *{nom_resto}* !\n\n"
            "Nous rencontrons un problème technique pour afficher notre menu.\n"
            "Veuillez réessayer dans quelques instants ou nous contacter directement. 🙏"
        )
        send_text_message(config, phone, fallback_msg)
    else:
        logger.info("send_interactive_menu → List Message envoyé à %s (%d sections)", phone, len(sections))


# Alias backward-compat — l'ancien nom est conservé pour ne pas casser les imports existants
send_main_menu = send_interactive_menu


# =============================================================================
# RECHERCHE PRODUIT — Retrouver un article par ID dans menu_data
# =============================================================================

def find_product_in_menu(menu_data, product_id: str) -> dict | None:
    """
    Parcourt menu_data (3 formats Supabase) et retourne le dict produit
    correspondant à product_id, ou None si introuvable.

    Formats supportés :
      1. {"categories": [{"name": "Burgers", "items": [{"id": …, "options": […]}]}]}
      2. [{"id": …, "category": "Burgers", "options": […]}]
      3. {"Burgers": [{"id": …, "options": […]}], …}

    :param menu_data: Catalogue JSONB issu de Supabase (snacks.menu_data).
    :param product_id: Identifiant du produit à rechercher (str).
    :return: Dict produit complet (incl. 'options' si présent) ou None.
    """
    if not menu_data or not product_id:
        return None

    pid = str(product_id)

    # Format 1 — dict avec clé "categories"
    if isinstance(menu_data, dict) and "categories" in menu_data:
        for cat in menu_data.get("categories", []):
            for item in cat.get("items", []):
                if str(item.get("id", "")) == pid or str(item.get("name", "")) == pid:
                    return item

    # Format 2 — liste plate
    elif isinstance(menu_data, list):
        for item in menu_data:
            if str(item.get("id", "")) == pid or str(item.get("name", "")) == pid:
                return item

    # Format 3 — dict de catégories
    elif isinstance(menu_data, dict):
        for _cat_name, items in menu_data.items():
            if _cat_name.startswith("_"):
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                if str(item.get("id", "")) == pid or str(item.get("name", "")) == pid:
                    return item

    return None


# =============================================================================
# OPTIONS PRODUIT — Envoi des boutons interactifs (max 3)
# =============================================================================

def send_product_options(config: dict, phone: str, product: dict) -> dict:
    """
    Envoie un message interactif WhatsApp à boutons (max 3) pour
    les options/modificateurs d'un produit.

    Chaque bouton porte un ID au format : opt_{product_id}_{option_id}
    (contrainte Meta : ID max 256 chars, titre max 20 chars).

    Si le produit possède > 3 options, seules les 3 premières sont affichées
    (contrainte Meta sur les reply buttons).

    :param config:  Dict issu de supabase_tool.get_snack_config().
    :param phone:   Numéro du client au format E.164.
    :param product: Dict produit complet (issu de find_product_in_menu).
                    Doit contenir la clé 'options' (list de dicts).
    :return:        Réponse JSON de Meta ou dict d'erreur.
    """
    from layer3_tools.whatsapp_tool import send_interactive_buttons

    product_id   = str(product.get("id") or product.get("name", "?"))
    product_name = str(product.get("name", "Article"))
    options      = product.get("options", [])

    if not options:
        logger.warning(
            "send_product_options : produit '%s' sans options — appel ignoré.",
            product_id,
        )
        return {"error": "no_options"}

    # Construire les boutons (max 3 — contrainte Meta)
    buttons = []
    for opt in options[:3]:
        opt_id   = str(opt.get("id") or opt.get("name", "?"))
        opt_name = str(opt.get("name", "Option"))
        btn_id   = f"opt_{product_id}_{opt_id}"[:256]

        buttons.append({
            "id":    btn_id,
            "title": opt_name[:20],
        })

    if len(options) > 3:
        logger.warning(
            "send_product_options : produit '%s' a %d options, seules les 3 premières affichées.",
            product_id, len(options),
        )

    price_str = ""
    price = product.get("price")
    if isinstance(price, (int, float)):
        price_str = f"\n💰 {price:.2f}€"

    result = send_interactive_buttons(
        config=config,
        recipient_phone=phone,
        header_text=f"🔧 Options — {product_name}"[:60],
        body_text=(
            f"Vous avez choisi *{product_name}*.{price_str}\n\n"
            "Sélectionnez votre option :"
        ),
        footer_text="SnackFlow • Commande rapide",
        buttons=buttons,
    )

    if result and "error" not in result:
        logger.info(
            "send_product_options → %d bouton(s) envoyés pour '%s' à %s",
            len(buttons), product_name, phone,
        )
    else:
        logger.error(
            "send_product_options : échec envoi options pour '%s' : %s",
            product_name, result.get("error"),
        )

    return result
