---
name: Skill_Safety_Gate
description: Protection & Compliance Protocol — Garantit qu'aucune donnée sensible ou faille de sécurité n'est introduite dans SnackFlow durant les phases de build ou de test.
---

# 🔐 Skill_Safety_Gate | Protection & Compliance Protocol

## 🎯 Objectif
Garantir qu'aucune donnée sensible ou faille de sécurité n'est introduite dans le système SnackFlow durant les phases de build ou de test.

---

## 🛡️ Protocoles Stricts

### 1. Zéro Hardcoding
**Règle absolue :** Aucune clé API, token, ou ID ne doit apparaître en dur dans le code source.

✅ **Pattern autorisé :**
```python
import os
token = os.getenv("WHATSAPP_ACCESS_TOKEN")
if not token:
    raise ValueError("WHATSAPP_ACCESS_TOKEN manquant dans .env")
```

❌ **Interdit :**
```python
token = "EAANec5rGMCABQ4..."  # JAMAIS
```

### 2. Validation .env
Avant chaque exécution, vérifier que toutes les variables requises (META_TOKEN, GS_ID, etc.) sont présentes dans le fichier `.env`.

```python
REQUIRED_VARS = [
    "GOOGLE_SHEET_ID",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_VERIFY_TOKEN",
    "DEFAULT_SNACK_ID",
]
missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    raise EnvironmentError(f"Variables .env manquantes : {missing}")
```

### 3. Isolation des Chemins
Utilisation systématique de `os.path.join` et `os.path.abspath` pour éviter les erreurs de répertoire (FileNotFoundError).

```python
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ACCOUNT = os.path.join(BASE_DIR, "service_account.json")
```

### 4. Sanitisation des Inputs
Tout message provenant de l'API WhatsApp doit être nettoyé avant d'être traité pour éviter les injections de scripts.

```python
import re

def sanitize_input(value: str, max_len: int = 255) -> str:
    cleaned = re.sub(r"[<>\"'%;()&+]", "", str(value))
    return cleaned[:max_len].strip()

# Usage dans le webhook
customer_phone = sanitize_input(data.get("customer_phone", ""))
choice = sanitize_input(data.get("choice", ""), max_len=2)
snack_id = sanitize_input(data.get("snack_id", DEFAULT_SNACK_ID), max_len=50)
```

### 5. Redaction des Logs
Ne jamais enregistrer les jetons d'accès ou les informations privées des clients dans les logs.

```python
def redact(value: str, visible: int = 6) -> str:
    if not value or len(value) <= visible:
        return "***"
    return value[:visible] + "***"

# Usage
print(f"Token actif : {redact(token)}")        # "EAANec***"
print(f"Client : {redact(phone, visible=5)}")  # "+3378***"
```

---

## 📋 Checklist de Validation (Pre-Commit)

- [ ] **Les clés sont-elles dans le .env ?** → `grep -r "EAA\|sk-" . --include="*.py"` → 0 résultat
- [ ] **Le .gitignore exclut-il bien les fichiers sensibles ?** → `.env`, `service_account.json`, `*.db`, `venv/` présents
- [ ] **Les chemins de fichiers sont-ils relatifs à la racine du projet ?** → `os.path.join(BASE_DIR, ...)` systématique

---

## 🚨 .gitignore Minimal SnackFlow

```gitignore
# Secrets
.env
service_account.json

# Base de données locale
*.db

# Environnement Python
venv/
__pycache__/
*.pyc

# Logs de test temporaires
flask_log.txt
test_log.txt
```

---

## 🔁 Invocation
Ce skill doit être invoqué **avant tout commit** ou **toute mise en production**.
