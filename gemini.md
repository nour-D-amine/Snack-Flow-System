# Project Constitution (Protocol Zero)

## North Star
"Transformer chaque appel entrant en une commande finalisée ou un transfert réussi, avec zéro friction pour le restaurateur."
Objectif concret : Automatiser l'envoi d'un lien de commande par SMS en < 3 secondes après le choix de l'utilisateur, et tracer chaque interaction.

## Integrations (Links)
1. **Twilio API** : Appels entrants, menu IVR (1 ou 2), SMS sortants.
2. **WhatsApp Business API** : Notifications structurées "Ticket Cuisine".
3. **Python Tooling** : Manipulation des numéros (E.164), génération de logs.

## Source of Truth
**Notion (Base de données 'Snack-Flow Master')** - CRM et registre de commandes.
- Contenu: Historique, téléphones, choix (1 ou 2), statut (Lien envoyé / Échec).

## Delivery Payload
- **Vers le Client** : SMS Twilio avec lien dynamique vers menu interactif.
- **Vers le Restaurant** : Message WhatsApp détaillé dès la fin de l'action IVR.

## Core Precepts
- Determinism
- Self-Healing
- Data-First

## Data Schemas
(To be defined in Phase 2/3)

## Behavioral Rules
- **Schema-First** : Always define the JSON schema before writing code.
- **Self-Healing** : If a tool fails, analyze the error and propose a fix automatically.
- **Determinism** : Logic must produce consistent results. No hallucination sur les prix/items. Uniquement les données de Notion.
- **Formatage E.164** : Normalisation au format international (ex: +33) avant tout envoi.
- **Fallback Rapide** : Si échec de SMS, notification WhatsApp immédiate d'échec pour rappel manuel.
- **Vitesse (Priorité asynchrone)** : Exécution asynchrone pour ne pas faire attendre le client.

## Architectural Invariants
- BLAST Framework
- ANT Layer Architecture (SOPs, Navigation, Tools)
