# Task Plan

## Phase 1: Blueprint (Vision & Logic)
- [x] Define the North Star
- [x] Identify Integrations
- [x] Source of Truth
- [x] Delivery Payload
- [x] Behavioral Rules

## Phase 2: Links (Connections)
- [x] Configure connections (via Python Native instead of MCP)
- [x] Perform verification handshakes (Google Sheets)
- [x] Store environment variables securely

## Phase 3: Architect (The Engine)
- [x] Layer 3 (Tools) : gsheets_tool, twilio_tool, whatsapp_tool, phone_tool
- [x] Layer 2 (Navigation) : ivr_flow.py — Flux IVR Flask (webhooks Twilio)
- [x] Layer 1 (SOPs) : orchestrator.py — SOP-001 à SOP-005 (démarrage, health, shutdown)

## Phase 4: Stylization (UI/UX)
- [ ] Refine formatting des messages SMS et WhatsApp
- [ ] Dashboard optionnel (si requis)

## Phase 5: Trigger (Deployment)
- [ ] Compléter les variables .env manquantes (TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID, RESTAURANT_WHATSAPP_NUMBER)
- [ ] Exposer le webhook (ngrok en dev, ou déploiement cloud en prod)
- [ ] Configurer le numéro Twilio pour pointer sur /incoming
- [ ] Test end-to-end complet (appel → IVR → SMS → WhatsApp → Google Sheets)
- [ ] Final security compliance audit
