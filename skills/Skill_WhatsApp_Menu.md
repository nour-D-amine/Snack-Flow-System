---
name: Skill_WhatsApp_Menu
description: Standardise la génération de messages interactifs WhatsApp pour garantir une interface utilisateur fluide et sans erreur de parsing JSON. Basé sur Meta WhatsApp Cloud API v19+.
---

# 📱 Skill_WhatsApp_Menu | Meta API Interaction Protocol

## 🎯 Objectif
Standardiser la génération de messages interactifs WhatsApp pour garantir une interface utilisateur fluide et sans erreur de parsing JSON.

> 📌 **Fichier d'implémentation** : `layer3_tools/whatsapp_tool.py`
> 📌 **Endpoint** : `https://graph.facebook.com/v19.0/{phone_number_id}/messages`

---

## 🛠️ Protocoles d'Interface

### Types de Messages autorisés

| Type | Usage SnackFlow | Limite |
|---|---|---|
| `button` | Choix simples (Menu / Rappel) | Max **3 boutons**, 20 car./titre |
| `list` | Sélections de catégories de menu | Max **10 options**, 24 car./titre |
| `text` | Confirmations, tickets cuisine, notifications | Max **1024 car.** corps |

### Règles structurelles (OBLIGATOIRES)

1. **`messaging_product`** : Toujours `"whatsapp"`
2. **`recipient_type`** : Toujours `"individual"`
3. **`snack_id` dans les payloads de bouton** : Passer le `snack_id` dans le champ `id` du bouton pour maintenir le contexte tenant lors du retour webhook
4. **Limites de taille** :
   - Titre de liste : max **24 caractères**
   - Texte de bouton `reply.title` : max **20 caractères**
   - Corps du message `body.text` : max **1024 caractères**
   - Footer : max **60 caractères**

---

## 📐 Templates JSON Standardisés

### Template 1 — `button` : Menu Client (2 boutons)

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+33785557054",
  "type": "interactive",
  "interactive": {
    "type": "button",
    "header": { "type": "text", "text": "🍔 Snack de Test" },
    "body": { "text": "Bonjour ! Comment puis-je vous aider ?" },
    "footer": { "text": "Snack-Flow • Commande en ligne" },
    "action": {
      "buttons": [
        {
          "type": "reply",
          "reply": { "id": "SNACK_TEST_01|btn_menu", "title": "Consulter Menu 🍔" }
        },
        {
          "type": "reply",
          "reply": { "id": "SNACK_TEST_01|btn_call", "title": "Appeler le Snack 📞" }
        }
      ]
    }
  }
}
```

> ⚠️ Le champ `id` doit contenir `snack_id|action` pour que le webhook sache à quel tenant appartient la réponse.

---

### Template 2 — `list` : Sélection de catégories menu

```json
{
  "messaging_product": "whatsapp",
  "recipient_type": "individual",
  "to": "+33785557054",
  "type": "interactive",
  "interactive": {
    "type": "list",
    "header": { "type": "text", "text": "🍽️ Notre Menu" },
    "body": { "text": "Choisissez une catégorie pour voir les plats disponibles." },
    "footer": { "text": "Snack-Flow" },
    "action": {
      "button": "Voir le menu",
      "sections": [
        {
          "title": "🥙 Sandwichs & Burgers",
          "rows": [
            { "id": "SNACK_TEST_01|cat_burgers", "title": "Burgers", "description": "Burgers maison" },
            { "id": "SNACK_TEST_01|cat_kebabs",  "title": "Kebabs",  "description": "Kebabs viande mixte" }
          ]
        },
        {
          "title": "🥤 Boissons & Desserts",
          "rows": [
            { "id": "SNACK_TEST_01|cat_drinks",  "title": "Boissons",  "description": "Froids & chauds" },
            { "id": "SNACK_TEST_01|cat_desserts","title": "Desserts",  "description": "Glaces, pâtisseries" }
          ]
        }
      ]
    }
  }
}
```

---

### Template 3 — `text` : Confirmation / Ticket Cuisine

```
📟 *NOUVELLE COMMANDE*
▬▬▬▬▬▬▬▬▬▬
👤 *Client :* +33785557054
🍔 *Détails :*
• 1x Burger Montagnard (Sauce Algérienne)
• 1x Frites Maison
• 1x Coca-Cola 33cl

💰 Total : 18.50€
▬▬▬▬▬▬▬▬▬▬
🕒 Heure : 14:10
📝 Notes : Sans oignons
```

---

## 📋 Fonctions Types (Logique à implémenter)

### `generate_category_list(config, customer_phone, categories)`

```python
def generate_category_list(config: dict, customer_phone: str, categories: list) -> dict:
    """
    Crée un message 'list' interactif avec les catégories du menu.
    :param categories: [{"title": "Burgers", "items": [{"id": "burger_01", "label": "Burger Maison"}]}]
    """
    snack_id = config["snack_id"]
    sections = []
    for cat in categories:
        rows = [
            {
                "id": f"{snack_id}|{item['id']}",       # snack_id contextualisé
                "title": item["label"][:24],             # max 24 car.
                "description": item.get("desc", "")[:72]
            }
            for item in cat.get("items", [])
        ]
        sections.append({"title": cat["title"][:24], "rows": rows})

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": customer_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": f"🍽️ {config['nom_resto']}"[:60]},
            "body": {"text": "Choisissez une catégorie :"},
            "footer": {"text": "Snack-Flow"},
            "action": {"button": "Voir le menu", "sections": sections}
        }
    }
```

---

### `generate_item_buttons(config, customer_phone, item_details)`

```python
def generate_item_buttons(config: dict, customer_phone: str, item_details: dict) -> dict:
    """
    Crée des boutons pour valider une sélection ou choisir une option.
    :param item_details: {"name": "Burger Maison", "price": "9.50", "options": ["Normal", "Spécial"]}
    """
    snack_id = config["snack_id"]
    options = item_details.get("options", ["Confirmer"])[:3]   # max 3 boutons
    buttons = [
        {
            "type": "reply",
            "reply": {
                "id": f"{snack_id}|{item_details['id']}|{opt.lower()[:10]}",
                "title": opt[:20]          # max 20 car.
            }
        }
        for opt in options
    ]

    price = item_details.get("price", "")
    body_text = f"*{item_details['name']}*\n💰 {price}€\n\nChoisissez une option :"
    if len(body_text) > 1024:
        body_text = body_text[:1021] + "..."

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": customer_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "footer": {"text": config["nom_resto"][:60]},
            "action": {"buttons": buttons}
        }
    }
```

---

### `generate_cart_summary(config, customer_phone, cart_json)`

```python
import json

def generate_cart_summary(config: dict, customer_phone: str, cart_json: str) -> dict:
    """
    Formate le panier pour une lecture claire avant confirmation.
    :param cart_json: JSON string issu de l'onglet COMMANDES.order_details
    """
    snack_id = config["snack_id"]
    try:
        items = json.loads(cart_json) if isinstance(cart_json, str) else cart_json
    except json.JSONDecodeError:
        items = [{"name": cart_json, "quantity": 1}]

    lines = []
    total = 0.0
    for item in items:
        qty  = item.get("quantity", 1)
        name = item.get("name", "Article")
        opts = " | ".join(item.get("options", []))
        price = float(item.get("price", 0))
        total += qty * price
        line = f"• {qty}x {name}"
        if opts:
            line += f" ({opts})"
        lines.append(line)

    body = (
        f"🛒 *Récapitulatif de votre commande :*\n\n"
        + "\n".join(lines)
        + f"\n\n💰 *Total : {total:.2f}€*\n\n✅ Confirmez-vous votre commande ?"
    )[:1024]

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": customer_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "footer": {"text": config["nom_resto"][:60]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"{snack_id}|confirm_yes", "title": "✅ Confirmer"}},
                    {"type": "reply", "reply": {"id": f"{snack_id}|confirm_no",  "title": "❌ Annuler"}}
                ]
            }
        }
    }
```

---

## ✅ Checklist de Conformité

- [ ] `messaging_product: "whatsapp"` présent dans tous les payloads
- [ ] `recipient_type: "individual"` présent dans tous les payloads
- [ ] `snack_id` intégré dans le champ `id` de chaque bouton/row (`snack_id|action`)
- [ ] Longueur des titres boutons ≤ 20 caractères (utiliser `[:20]`)
- [ ] Longueur des titres de liste ≤ 24 caractères (utiliser `[:24]`)
- [ ] Corps du message ≤ 1024 caractères (tronquer si nécessaire)
- [ ] Zéro token en dur — token récupéré depuis `config["whatsapp_token"]`
- [ ] Gestion `401` (token expiré) et `131030` (numéro non autorisé en dev)
