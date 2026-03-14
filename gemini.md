# Project Constitution (Protocol Zero) — v2.0 Full-WhatsApp

## North Star
"Transformer chaque message WhatsApp entrant en une commande confirmée, avec zéro friction pour le client et un ticket cuisine instantané pour le snack."
Objectif concret : Traiter un message WhatsApp entrant, logger la commande dans Supabase, envoyer une confirmation au client et un ticket cuisine au snack — le tout en < 3 secondes.

## Architecture Full-WhatsApp (pivot v2.0)
```
CLIENT WhatsApp
    │  message texte libre
    ▼
/webhook POST  (Layer 2 — whatsapp_webhook.py)
    │  parsing payload Meta réel
    │  exécution asynchrone
    ├──► upsert_customer()   → Supabase (Layer 3)
    ├──► log_order()         → Supabase (Layer 3)
    ├──► send_menu()         → WhatsApp Client (confirmation)
    └──► send_kitchen_ticket() → WhatsApp Snack (ticket cuisine)
```

## Integrations
1. **WhatsApp Business API (Meta Graph)** : Messages entrants (webhook), menus interactifs, tickets cuisine, remarketing.
2. **Supabase (PostgreSQL)** : Source de vérité unique — snacks, orders, customers, interactions.
3. **Python Tooling** : Normalisation E.164, parsing payload Meta, génération de logs.

## Source of Truth
**Supabase** (projet `SnackFlow-system`, région eu-west-3 Paris).
- `snacks`       → Configuration des restaurants (credentials WA, menu_url, seuil fidélité)
- `orders`       → Journal horodaté de chaque commande
- `customers`    → CRM clients (fidélité, remarketing)
- `interactions` → Historique des échanges WhatsApp

## Delivery Payload
- **Vers le Client** : Message WhatsApp interactif (bouton menu + confirmation commande).
- **Vers le Snack**  : Ticket cuisine WhatsApp formaté dès réception du message.

## Core Precepts
- Determinism
- Self-Healing
- Data-First

## Behavioral Rules
- **Schema-First** : Toujours définir le schéma JSON avant d'écrire le code.
- **Self-Healing** : Si WhatsApp ou Supabase échoue, logger l'erreur et continuer sans crash.
- **Determinism** : Uniquement les données Supabase. Aucun prix ou item inventé.
- **Formatage E.164** : Normalisation systématique avant tout INSERT ou envoi WhatsApp.
- **Fallback Rapide** : Si envoi WhatsApp échoue → log `status="Échec"` dans Supabase + alerte interne.
- **Vitesse (Priorité asynchrone)** : Réponse 202 immédiate au webhook Meta, traitement en thread.

## Ce qui est SUPPRIMÉ (v1 → v2)
- ~~Twilio~~ — aucun service vocal
- ~~IVR (menu 1/2)~~ — aucun appel téléphonique
- ~~SMS~~ — WhatsApp uniquement
- ~~Google Sheets~~ — Supabase uniquement
- ~~Notion~~ — Supabase uniquement
- ~~SQLite (crm_tool)~~ — Supabase uniquement

## Architectural Invariants
- BLAST Framework
- ANT Layer Architecture (SOPs → Navigation → Tools)
