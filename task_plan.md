# SnackFlow (api.menudirect.fr) - Project Task Plan

## Current Status
- **Pivot Stratégique Effectué** : Transition vers une architecture "100% WhatsApp" (Full-WhatsApp v2.0).
- **Objectif** : Transformer chaque message WhatsApp entrant en une commande confirmée, traitée et routée instantanément, avec zéro friction et sans usage de téléphonie, de Twilio ou d'IVR.

## Completed Tasks

### Phase 1: Blueprint & Architecture
- [x] Définition de la North Star (100% WhatsApp via Meta API, traitement < 3s).
- [x] Architecture : Layer 1 (SOPs), Layer 2 (Webhook Meta), Layer 3 (Outils).
- [x] Suppression complète des dépendances : Twilio, flux IVR, appels téléphoniques, SMS, phone_tool.py.
- [x] Pivot vers **Supabase** comme point de vérité unique (snacks, orders, customers).

### Phase 2: Infrastructure & Déploiement
- [x] **Configuration DNS Hostinger** : Validation des enregistrements pour le domaine `api.menudirect.fr`.
- [x] **SSL Railway** : Génération et activation du certificat TLS/SSL.
- [x] **Liaison du domaine** : Configuration du routage avec `api.menudirect.fr` sur l'environnement Railway.
- [x] Sécurisation des variables d'environnement initiales.

### Phase 3: Core Logic (The Engine)
- [x] Layer 3 (Tools) : `supabase_tool.py`, `whatsapp_tool.py`, `gemini_tool.py`.
- [x] Layer 2 (Navigation) : Création de `whatsapp_webhook.py` (remplacement intégral de l'IVR).
- [x] Layer 1 (SOPs) : Modernisation de `orchestrator.py`.

## Next Steps

### Phase 4: Stylization (UI/UX)
- [ ] Affinage du formatage des messages interactifs WhatsApp (Menu avec boutons).
- [ ] Optimisation de la structure et du rendu visuel du "ticket cuisine" WhatsApp reçu par le restaurant.

### Phase 5: Trigger & Launch
- [ ] Configuration stricte des variables d'environnement critiques en production (`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_PHONE_NUMBER_ID`).
- [ ] **Validation du Webhook** dans le dashboard Meta Developers (via le endpoint sécurisé `https://api.menudirect.fr/webhook`).
- [ ] **Abonnement de Webhook** : Souscrire explicitement au champ `messages` dans la configuration WhatsApp Cloud API de Meta.
- [ ] Tests de bout en bout de la réception de commande.
- [ ] Tests de parsing de texte avec **Gemini** (détection et extraction fiable des items de la commande).
- [ ] Audit final de sécurité (Vérifications des signatures Meta X-Hub-Signature-256) et conformité (RGPD).
