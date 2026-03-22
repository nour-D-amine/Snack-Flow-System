# CONTRAT DE SOUS-TRAITANCE DE DONNÉES PERSONNELLES
### Conforme au Règlement (UE) 2016/679 (RGPD) — Article 28

---

**Entre les soussignés :**

**Le Responsable de traitement (le Client) :**
- Raison sociale : ___________________________________
- SIRET : ___________________________________
- Adresse : ___________________________________
- Représentant légal : ___________________________________
- Email DPO / contact RGPD : ___________________________________

ci-après désigné **« le Responsable »**,

**ET**

**Le Sous-traitant :**
- Raison sociale : Snack-Flow (ou la société exploitant la plateforme)
- SIRET : ___________________________________
- Adresse : ___________________________________
- Représentant légal : ___________________________________
- Email DPO : ___________________________________

ci-après désigné **« le Sous-traitant »**,

---

## Article 1 — Objet et durée

Le présent contrat définit les conditions dans lesquelles le Sous-traitant traite des données personnelles pour le compte du Responsable dans le cadre de l'utilisation de la plateforme **Snack-Flow** (gestion des commandes WhatsApp, CRM client, système de fidélité).

**Durée :** Le présent contrat prend effet à la date de signature et reste en vigueur pendant toute la durée de la relation commerciale entre les parties.

---

## Article 2 — Nature et finalité des traitements

| Paramètre | Détail |
|---|---|
| **Nature** | Collecte, enregistrement, conservation, mise à disposition, suppression |
| **Finalité** | Gestion des commandes WhatsApp, fidélisation client, remarketing opt-in |
| **Type de données** | Numéros de téléphone (E.164), historique de commandes, préférences |
| **Personnes concernées** | Clients finaux du Responsable (acheteurs) |
| **Durée de conservation** | 3 ans à compter du dernier contact, puis suppression automatique |

---

## Article 3 — Obligations du Sous-traitant (Art. 28(3) RGPD)

Le Sous-traitant s'engage à :

**3.1 Traitement sur instruction uniquement**
Ne traiter les données personnelles que sur instruction documentée du Responsable, sauf obligation légale contraire.

**3.2 Confidentialité**
Garantir que les personnes autorisées à traiter les données sont soumises à une obligation de confidentialité.

**3.3 Sécurité (Art. 32 RGPD)**
Mettre en œuvre les mesures techniques et organisationnelles appropriées, notamment :
- Chiffrement des données en transit (HTTPS/TLS 1.2+) et au repos (AES-256 via Supabase)
- Authentification multi-tenant par signature HMAC-SHA256 (Meta Webhook)
- Isolation des données par tenant (Row Level Security Supabase)
- Contrôle d'accès administrateur par token Bearer (endpoint RGPD)

**3.4 Sous-traitants ultérieurs**
Ne pas recruter de sous-traitant ultérieur sans autorisation préalable écrite du Responsable. Les sous-traitants ultérieurs actuellement autorisés sont :

| Sous-traitant | Rôle | Localisation | DPA |
|---|---|---|---|
| Supabase Inc. | Base de données PostgreSQL | UE (eu-west-3) | [DPA Supabase](https://supabase.com/privacy) |
| Google LLC (Gemini) | Parsing LLM des commandes | USA (SCC applicables) | [DPA Google](https://cloud.google.com/terms/data-processing-addendum) |
| Meta Platforms | Transport WhatsApp | USA (SCC applicables) | [Conditions Meta](https://www.whatsapp.com/legal/business-terms) |

**3.5 Droits des personnes**
Aider le Responsable à répondre aux demandes d'exercice des droits (accès, rectification, effacement, portabilité) dans un délai maximum de **72 heures** suivant la réception de la demande. L'endpoint `/admin/gdpr/delete` est mis à disposition à cet effet.

**3.6 Notification de violation (Art. 33 RGPD)**
Notifier le Responsable de toute violation de données personnelles dans un délai de **24 heures** suivant la découverte, avec les informations requises par l'Art. 33(3) RGPD.

**3.7 Analyse d'impact (DPIA)**
Aider le Responsable à réaliser une analyse d'impact (DPIA) si le traitement est susceptible d'engendrer un risque élevé.

**3.8 Audit**
Mettre à disposition du Responsable toutes les informations nécessaires pour démontrer le respect des obligations du présent article, et permettre des audits (y compris inspections) conduits par le Responsable ou un auditeur mandaté.

**3.9 Suppression en fin de contrat**
À l'issue de la prestation, supprimer ou restituer toutes les données personnelles au Responsable, et détruire les copies existantes, sauf obligation légale de conservation.

---

## Article 4 — Obligations du Responsable de traitement

Le Responsable s'engage à :
- Fournir une base légale valide pour chaque traitement (Art. 6 RGPD)
- Informer les personnes concernées de leurs droits (notice RGPD envoyée par la plateforme au 1er contact)
- Ne pas activer le remarketing (`remarketing_eligible`) sans recueil préalable du consentement explicite de chaque client (Art. 7 RGPD)
- Signaler au Sous-traitant toute demande d'exercice de droits dans un délai de **48 heures**
- Désigner un DPO si applicable (Art. 37 RGPD)

---

## Article 5 — Transferts hors UE

Les transferts vers Google (Gemini) et Meta (WhatsApp) sont encadrés par des **Clauses Contractuelles Types (CCT)** adoptées par la Commission européenne (décision 2021/914). Le Responsable reconnaît et accepte ces transferts aux conditions définies à l'Article 3.4.

---

## Article 6 — Responsabilité

En cas de manquement aux obligations du présent contrat imputable au Sous-traitant, celui-ci engage sa responsabilité vis-à-vis du Responsable dans les limites prévues au contrat commercial principal.

---

## Article 7 — Loi applicable et juridiction

Le présent contrat est soumis au droit français. Tout litige relatif à son interprétation ou son exécution sera soumis aux tribunaux compétents de Paris.

---

## Signatures

| Responsable de traitement | Sous-traitant (Snack-Flow) |
|---|---|
| Nom : ___________________ | Nom : ___________________ |
| Fonction : _______________ | Fonction : _______________ |
| Date : ___________________ | Date : ___________________ |
| Signature : ______________ | Signature : ______________ |

---

*Document généré conformément au RGPD (UE) 2016/679 — Art. 28. À faire valider par un juriste ou DPO avant signature.*
