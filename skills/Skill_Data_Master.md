---
name: Skill_Data_Master
description: Standardise toutes les opérations de lecture/écriture sur le Google Sheet Master pour garantir l'isolation des données par restaurant (tenant) dans SnackFlow.
---

# 📊 Skill_Data_Master | Multi-Tenant GSheets Protocol

## 🎯 Objectif
Standardiser toutes les opérations de lecture/écriture sur le Google Sheet Master pour garantir l'isolation des données par restaurant.

---

## �️ Architecture des Onglets

| Onglet | Rôle | Colonnes |
|---|---|---|
| **RESTOS** | Configuration restaurants | `snack_id`, `nom_resto`, `whatsapp_phone_id`, `whatsapp_token`, `menu_url`, `loyalty_threshold`, `resto_phone` |
| **COMMANDES** | Log des transactions | `timestamp`, `snack_id`, `customer_phone`, `order_details`, `status` |

---

## �️ Protocoles d'Opération

### ① Isolation par Snack_ID (OBLIGATOIRE)
Toute requête de lecture (GET) ou d'écriture (APPEND) doit obligatoirement inclure un `snack_id` validé.

```python
# ✅ Correct — snack_id systématique
def log_new_order(data_dict: dict):
    snack_id = data_dict.get("snack_id")
    if not snack_id:
        raise ValueError("snack_id obligatoire pour tout log de commande")
    ...

# ❌ Interdit — lecture globale sans filtre tenant
records = ws.get_all_records()  # seul usage OK : pour get_snack_config()
```

### ② Mapping Dynamique des Colonnes (OBLIGATOIRE)
Ne jamais utiliser d'index de colonne fixe. Toujours résoudre la position depuis l'en-tête.

```python
# ✅ Correct — résolution dynamique
def _col_index(headers: list, col_name: str) -> int:
    """Retourne l'index 1-based de la colonne depuis le header."""
    try:
        return headers.index(col_name) + 1
    except ValueError:
        raise KeyError(f"Colonne '{col_name}' introuvable dans les en-têtes : {headers}")

# Usage :
rows = ws.get_all_values()
headers = rows[0]
status_col = _col_index(headers, "status")
ws.update_cell(target_row, status_col, "Lien envoyé")

# ❌ Interdit
ws.update_cell(target_row, 5, "Lien envoyé")  # Index fixe = fragile
```

### ③ Formatage JSON pour les Commandes Complexes
Les listes d'items doivent être stockées en JSON string dans une seule cellule.

```python
import json

# ✅ Stockage
items = [
    {"name": "Burger Montagnard", "quantity": 1, "options": ["Sauce Algérienne"]},
    {"name": "Frites Maison", "quantity": 1},
]
order_details_json = json.dumps(items, ensure_ascii=False)
# → '[{"name": "Burger Montagnard", "quantity": 1, "options": ["Sauce Algérienne"]}, ...]'

# ✅ Relecture
items_back = json.loads(order_details_json)
```

### ④ Gestion des Fallbacks (DEFAULT_SNACK_ID)
Si un `snack_id` est introuvable dans RESTOS, rediriger vers le fallback défini dans `.env`.

```python
import os

DEFAULT_SNACK_ID = os.getenv("DEFAULT_SNACK_ID", "")

def get_restaurant_config(snack_id: str) -> dict:
    try:
        return get_snack_config(snack_id)
    except KeyError:
        if DEFAULT_SNACK_ID and snack_id != DEFAULT_SNACK_ID:
            print(f"⚠️  snack_id '{snack_id}' introuvable. Fallback → {DEFAULT_SNACK_ID}")
            return get_snack_config(DEFAULT_SNACK_ID)
        raise
```

---

## 📋 Fonctions Types (Interface Standardisée)

### `get_restaurant_config(identifier: str) -> dict`
Recherche par `snack_id` ou numéro de téléphone. Retourne le dict complet du tenant.

```python
def get_restaurant_config(identifier: str) -> dict:
    """
    Recherche par snack_id ou par resto_phone.
    :param identifier: snack_id (ex: 'SNACK_01') ou E.164 (ex: '+33612345678')
    :return: dict config complet du restaurant
    """
    sh = _get_spreadsheet()
    ws = sh.worksheet("RESTOS")
    records = ws.get_all_records()

    for record in records:
        if record.get("snack_id") == identifier or record.get("resto_phone") == identifier:
            record["loyalty_threshold"] = int(record.get("loyalty_threshold", 0) or 0)
            return record

    # Fallback
    default = os.getenv("DEFAULT_SNACK_ID", "")
    if default and default != identifier:
        return get_restaurant_config(default)

    raise KeyError(f"Restaurant '{identifier}' introuvable (et aucun DEFAULT_SNACK_ID valide)")
```

---

### `log_new_order(data_dict: dict) -> dict`
Ajoute une ligne dans COMMANDES avec timestamp ISO-8601.

```python
import json
from datetime import datetime

def log_new_order(data_dict: dict) -> dict:
    """
    Ajoute une commande dans l'onglet COMMANDES.
    data_dict doit contenir : snack_id, customer_phone, items (list), total, status
    """
    snack_id = data_dict.get("snack_id")
    if not snack_id:
        return {"status": "error", "message": "snack_id obligatoire"}

    items = data_dict.get("items", [])
    order_details = json.dumps(items, ensure_ascii=False) if isinstance(items, list) else str(items)

    row = [
        datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),  # ISO-8601
        snack_id,
        data_dict.get("customer_phone", ""),
        order_details,                                   # JSON string
        data_dict.get("status", "En attente"),
    ]

    sh = _get_spreadsheet()
    ws = sh.worksheet("COMMANDES")
    ws.append_row(row, value_input_option="USER_ENTERED")
    return {"status": "success", "row": row}
```

---

### `update_order_status(snack_id: str, customer_phone: str, new_status: str) -> bool`
Recherche ciblée et mise à jour par mapping dynamique de colonnes.

```python
def update_order_status(snack_id: str, customer_phone: str, new_status: str) -> bool:
    """
    Met à jour le statut de la dernière commande correspondant à snack_id + customer_phone.
    Utilise la résolution dynamique des colonnes (pas d'index fixe).
    """
    sh = _get_spreadsheet()
    ws = sh.worksheet("COMMANDES")
    rows = ws.get_all_values()
    headers = rows[0]

    snack_col   = _col_index(headers, "snack_id")       - 1  # 0-based pour itération
    phone_col   = _col_index(headers, "customer_phone") - 1
    status_col  = _col_index(headers, "status")              # 1-based pour update_cell

    # Parcours inversé pour trouver la DERNIÈRE commande
    for idx in range(len(rows) - 1, 0, -1):
        row = rows[idx]
        if row[snack_col] == snack_id and row[phone_col] == customer_phone:
            ws.update_cell(idx + 1, status_col, new_status)
            print(f"✅ Statut mis à jour → {new_status} (ligne {idx+1})")
            return True

    print(f"⚠️  Commande introuvable : {snack_id} / {customer_phone}")
    return False
```

---

## ✅ Checklist de Conformité (à vérifier sur gsheets_tool.py)

- [ ] Toujours passer `snack_id` en paramètre — jamais de lecture globale non filtrée
- [ ] Résolution dynamique des colonnes via `_col_index(headers, nom)` — pas d'index fixe
- [ ] JSON string pour `order_details` si items est une liste
- [ ] Timestamp ISO-8601 : `datetime.now().strftime("%Y-%m-%dT%H:%M:%S")`
- [ ] Fallback `DEFAULT_SNACK_ID` si tenant inconnu
- [ ] `loyalty_threshold` casté en `int` après lecture GSheets
- [ ] Gestion d'exception sur tout appel `ws.worksheet()` (WorksheetNotFound)

---

## ⚡ Règles d'Optimisation API

| Opération | Méthode optimisée |
|---|---|
| Lire config tenant | `ws.get_all_records()` une fois, filtrer en Python |
| Log commande | `ws.append_row()` |
| Mise à jour statut | `ws.update_cell(row, col_dynamic)` |
| Vérification fidélité | `ws.get_all_values()` + comptage Python |

> 🚀 **Objectif** : ≤ 2 appels API Google Sheets par requête webhook.
