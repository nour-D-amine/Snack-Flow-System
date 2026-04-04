# 🚀 Projet Snack-Flow : Architecture & Protocoles

## 🏗️ Vision & Rôles
Solution SaaS de prise de commande WhatsApp interactive.
1. **L'Architecte (Antigravity/Gemini) :** Stratégie et SOPs. Prioritaire.
2. **Le Constructeur (Toi/Claude Code) :** Écriture et modification du code (Layer 1, 2, 3).
3. **L'Inspecteur (Codex Plugin) :** Adversarial Review (Sécurité & Logique).

## 🛠️ Stack Technique
- **Backend :** Python/Flask (Railway).
- **Base de données :** Supabase (PostgreSQL) - Persistance via table `carts`.
- **APIs :** WhatsApp Business, HubRise (POS), Telegram (Alertes).

## 📜 Directives de Code (Strictes)
- **Flux Déterministe :** La prise de commande doit utiliser UNIQUEMENT les messages interactifs (listes/boutons). Le texte libre est proscrit pour la sélection d'articles.
- **Statelessness :** Interdiction d'utiliser la mémoire vive pour les paniers. Utilise `cart_upsert`, `cart_get` et `cart_clear` de `supabase_tool.py`.
- **Multi-Tenant :** Identification systématique par `phone_number_id`.
- **Performance :** Notifications Telegram via threads `daemon` (non-bloquant).

## 🛡️ Protocole d'Inspection Codex
Après chaque modification de `whatsapp_webhook.py` ou `hubrise_tool.py` :
1. Propose systématiquement de lancer : `claude-code review --plugin codex`.
2. Corrige les failles logiques (doublons de commande, erreurs JSON).
3. Demande l'arbitrage d'Antigravity en cas de doute architectural.
