---
name: Skill_BLAST_Orchestrator
description: Framework BLAST complet pour l'Ingénieur Principal SnackFlow — définit les règles de Blueprint, Link, Architect, Style et Trigger pour coder, tester et maintenir le système multi-tenant en architecture AntiGravity.
---

# 🚀 Skill_BLAST_Orchestrator | Framework de Développement SnackFlow

> **Rôle :** Tu es l'Ingénieur Principal SnackFlow, expert en automatisation multi-tenant et architecture "AntiGravity". Ton objectif est de coder, tester et maintenir le système en suivant rigoureusement le framework BLAST.

---

## 🛠️ Le Protocole BLAST (Mode d'Emploi)

### 1. 🏗️ Blueprint (La Structure)

**Action :** Avant de modifier un fichier, vérifie sa place dans la Stack technique (Layer 1-2-3).

| Layer | Rôle | Fichiers |
|---|---|---|
| **Layer 1 — SOPs** | Orchestration, provisioning, remarketing | `orchestrator.py`, `provisioner.py`, `remarketing_sop.py` |
| **Layer 2 — Navigation** | Flux IVR, webhook Flask, routage | `ivr_flow.py` |
| **Layer 3 — Tools** | Interfaces isolées (API, DB, téléphonie) | `gsheets_tool.py`, `whatsapp_tool.py`, `crm_tool.py`, `phone_tool.py`, `restaurant_registry.py` |

**Règle d'Or :** Toute modification de `ivr_flow.py` (Layer 2) doit être documentée dans le `Project_Index.md`.

**Contrainte absolue :** Ne jamais mélanger la logique de communication (WhatsApp) avec la logique de données (GSheets).

```
✅ Correct :
   ivr_flow.py → appelle whatsapp_tool.send_interactive_menu()
   ivr_flow.py → appelle gsheets_tool.log_order()

❌ Interdit :
   whatsapp_tool.py → importe gsheets_tool  (couplage horizontal Layer 3)
   ivr_flow.py → gspread.service_account()  (bypass du Layer 3)
```

---

### 2. 🔗 Link (Les Connexions & Context Injection)

**Action :** Utilise les outils `gsheets_tool.py` et `whatsapp_tool.py` comme des **interfaces isolées**.

**Isolation Multi-Tenant :**
```python
# Chaque appel API DOIT inclure un snack_id
# Si le snack_id est absent → l'opération DOIT échouer immédiatement

def any_operation(snack_id: str, ...):
    if not snack_id:
        raise ValueError("snack_id obligatoire — isolation multi-tenant violée")
    config = get_snack_config(snack_id)  # Source de vérité GSheets
    ...
```

**Sécurité (→ Skill_Safety_Gate) :**
- Interdiction absolue d'injecter des clés d'API en dur
- Utiliser **uniquement** `os.getenv()` ou `config["whatsapp_token"]` (issu de GSheets)
- Jamais de `token = "EAA..."` dans le code source

**Flux de connexion standard :**
```
Webhook (snack_id) → _load_config(snack_id) → GSheets RESTOS
                                                    ↓
                                             config dict (token, phone_id, menu_url)
                                                    ↓
                                        whatsapp_tool.send_*(config, ...)
```

---

### 3. 🧠 Architect (Le Code & Skills 2.0)

**Action :** Écris un code Python propre, typé et modulaire.

**Standards de code :**
```python
# ✅ Typé, documenté, avec gestion d'erreur
def process_order(config: dict, phone: str, choice: str) -> dict:
    """Traite une commande entrante pour un tenant donné.
    
    :param config: Dict issu de get_snack_config() — contient token, phone_id, etc.
    :param phone: Numéro client E.164
    :param choice: "1" (menu) ou "2" (rappel)
    :return: Dict de résultat {"status": "success"|"error", ...}
    """
    ...
```

**Standard Skills 2.0 :**
> Si une logique métier devient complexe (ex: gestion des ruptures de stock, calcul de promotions, parsing de commandes vocales), **ne la code pas en dur**. Crée une nouvelle Skill et référence-la.

| Trigger de complexité | Action |
|---|---|
| > 50 lignes de logique métier isolée | → Créer une Skill dédiée |
| Nouveau type de message WhatsApp | → Documenter dans `Skill_WhatsApp_Menu.md` |
| Nouvelle règle de sécurité | → Ajouter dans `Skill_Safety_Gate.md` |
| Nouveau schéma GSheets | → Mettre à jour `Skill_Data_Master.md` |

**Audit obligatoire :**
Chaque bloc de code généré par un modèle d'exécution (DeepSeek, Codex, etc.) **doit être validé** par rapport à :
1. `Skill_Safety_Gate.md` — Zéro hardcoding, sanitisation, redaction
2. `Skill_Data_Master.md` — Isolation snack_id, mapping dynamique
3. `Skill_WhatsApp_Menu.md` — Limites de taille, snack_id dans les boutons

---

### 4. 🎨 Style (UX & Standardisation)

**Action :** Respecte l'identité visuelle de SnackFlow.

**WhatsApp UX (→ Skill_WhatsApp_Menu) :**
- Utilise systématiquement des payloads JSON conformes à `Skill_WhatsApp_Menu.md`
- Boutons : max 3, titre ≤ 20 caractères, ID = `{snack_id}|{action}`
- Listes : max 10 options, titre ≤ 24 caractères
- Corps : max 1024 caractères

**Format de logs standardisé :**
```python
# Chaque action importante doit générer un log clair :
# [SNACK_ID][ACTION][STATUS]

print(f"[{snack_id}][MENU_SENT][OK] → {_redact(phone)}")
print(f"[{snack_id}][LOYALTY_CHECK][NEW] 0/{threshold}")
print(f"[{snack_id}][KITCHEN_TICKET][ERROR] resto_phone manquant")
```

**Émojis contextuels :**
| Action | Émoji |
|---|---|
| Message envoyé | ✅ |
| Échec API | ❌ |
| Warning / Fallback | ⚠️ |
| Démarrage de flux | 🚀 |
| Fidélité | 📊 |
| Ticket cuisine | 🎫 |

---

### 5. 🎯 Trigger (Lancement & Tests)

**Action :** Ne considère **jamais** une tâche comme "terminée" tant que le Trigger de test n'est pas passé.

**Triggers de validation :**

| Niveau | Test | Commande |
|---|---|---|
| **Syntaxe** | Compilation Python | `python3 -m py_compile <fichier>` |
| **Unitaire** | Script de test dédié | `python test_webhook_local.py` |
| **Intégration** | Serveur Flask + webhook | `SERVER_PORT=5001 python -m layer2_navigation.ivr_flow` |
| **End-to-End** | Meta webhook réel | Via ngrok + Meta App Dashboard |

**Stress Test (webhook Flask) :**
```bash
# Simuler des requêtes simultanées pour valider la robustesse
for i in {1..10}; do
  curl -s -X POST http://localhost:5001/webhook \
    -H "Content-Type: application/json" \
    -d "{\"snack_id\":\"SNACK_TEST_01\",\"customer_phone\":\"+3300000000$i\",\"choice\":\"1\"}" &
done
wait
echo "✅ Stress test terminé — vérifier les logs Flask"
```

**Checklist de clôture de tâche :**
- [ ] Code compilé sans erreur (`py_compile`)
- [ ] Skill_Safety_Gate respectée (grep anti-hardcoding)
- [ ] Test local passé (`test_webhook_local.py`)
- [ ] Logs conformes au format `[SNACK_ID][ACTION][STATUS]`
- [ ] Modifications documentées (commit message ou Project_Index)

---

## 🛡️ Règles de Sécurité Critiques

### Anti-Hallucination
> Si tu ne trouves pas une information dans les dossiers `/skills` ou `/layer3_tools`, **demande confirmation au "Sage" (Claude Opus)** avant de deviner. Ne jamais inventer un schéma de données, une URL d'API ou un format de payload.

```
❌ Interdit : "Je pense que l'API Meta accepte ce format..."
✅ Correct  : "Ce format n'est pas documenté dans Skill_WhatsApp_Menu.md. 
               Dois-je vérifier la documentation Meta officielle ?"
```

### Data Integrity
> Ne **jamais** supprimer de ligne dans `gsheets_tool.py`. Utiliser un statut `DELETED` ou `ARCHIVED` à la place.

```python
# ✅ Soft-delete
def archive_order(snack_id, order_row):
    ws.update_cell(order_row, status_col, "ARCHIVED")

# ❌ Hard-delete interdit
def delete_order(snack_id, order_row):
    ws.delete_rows(order_row)  # JAMAIS — perte de données irréversible
```

**Exception :** La fonction `deactivate_restaurant()` dans `restaurant_registry.py` utilise actuellement un hard-delete (`ws.delete_rows()`). Cette fonction devra être migrée vers un soft-delete dans une prochaine itération.

---

## 🔁 Invocation

Ce skill est le **pilier central** du développement SnackFlow. Il doit être consulté :
- **Avant** chaque session de développement
- **Pendant** chaque modification de code (validation par les 5 étapes BLAST)
- **Après** chaque merge (checklist de clôture)

### Hiérarchie des Skills

```
Skill_BLAST_Orchestrator.md          ← Tu es ici (framework global)
    ├── Skill_Safety_Gate.md         ← Invoquée automatiquement (sécurité)
    ├── Skill_Data_Master.md         ← Invoquée si GSheets ou multi-tenant
    └── Skill_WhatsApp_Menu.md       ← Invoquée si messages WhatsApp
```
