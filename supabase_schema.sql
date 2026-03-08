-- =============================================================================
-- Snack-Flow — Schéma SQL Supabase (PostgreSQL)
-- =============================================================================
-- Architecture : Multi-Tenant via snack_id (isolation par restaurant)
-- Exécuter dans : Supabase Dashboard → SQL Editor → Nouveau script
--
-- Tables :
--   1. snacks        → Configuration des restaurants (remplace GSheets RESTOS)
--   2. orders        → Journal des commandes (remplace GSheets COMMANDES)
--   3. customers     → Profils clients CRM (remplace SQLite clients)
--   4. interactions  → Historique appels IVR (remplace SQLite interactions)
--
-- Règles :
--   - Chaque table porte un snack_id (FK vers snacks) pour l'isolation tenant.
--   - Row Level Security (RLS) activé — accès via service_role uniquement côté serveur.
--   - UUID généré automatiquement par Supabase (gen_random_uuid()).
--   - Timestamps en UTC (timestamptz).
-- =============================================================================


-- ─────────────────────────────────────────────────────────────────────────────
-- EXTENSION UUID (activée par défaut sur Supabase, idempotent)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =============================================================================
-- 1. TABLE : snacks
--    Source de vérité des configurations restaurant.
--    Remplace l'onglet GSheets 'RESTOS'.
-- =============================================================================

CREATE TABLE IF NOT EXISTS snacks (
    -- Identifiant unique du restaurant (ex: "SNACK_PARIS_01")
    snack_id            TEXT PRIMARY KEY,

    -- Nom affiché dans les messages WhatsApp
    nom_resto           TEXT NOT NULL,

    -- Credentials WhatsApp Business API (Meta Graph)
    whatsapp_phone_id   TEXT NOT NULL,
    whatsapp_token      TEXT NOT NULL,

    -- URL du menu interactif envoyé par WhatsApp
    menu_url            TEXT DEFAULT '',

    -- Nombre de commandes pour déclencher le statut LOYAL
    loyalty_threshold   INTEGER NOT NULL DEFAULT 5,

    -- Numéro de téléphone public du restaurant (format E.164)
    resto_phone         TEXT DEFAULT '',

    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index utile pour les lookups fréquents
CREATE INDEX IF NOT EXISTS idx_snacks_resto_phone ON snacks (resto_phone);

-- Trigger mise à jour automatique de updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS snacks_updated_at ON snacks;
CREATE TRIGGER snacks_updated_at
    BEFORE UPDATE ON snacks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Row Level Security
ALTER TABLE snacks ENABLE ROW LEVEL SECURITY;

-- Seul le service_role peut lire/écrire (pas d'accès anon)
CREATE POLICY "Service role only" ON snacks
    USING (auth.role() = 'service_role');


-- =============================================================================
-- 2. TABLE : orders
--    Journal horodaté de toutes les commandes (tous tenants).
--    Remplace l'onglet GSheets 'COMMANDES'.
-- =============================================================================

CREATE TABLE IF NOT EXISTS orders (
    -- Clé primaire auto-générée
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Référence restaurant (Multi-Tenant)
    snack_id            TEXT NOT NULL REFERENCES snacks(snack_id) ON DELETE CASCADE,

    -- Numéro client au format E.164
    customer_phone      TEXT NOT NULL,

    -- Description de la commande (libre ou JSON stringifié)
    order_details       TEXT DEFAULT '',

    -- Statut : "Lien envoyé" | "Échec" | "En attente"
    status              TEXT NOT NULL DEFAULT 'En attente'
                            CHECK (status IN ('Lien envoyé', 'Échec', 'En attente')),

    -- Timestamp UTC
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour les requêtes fréquentes par tenant + client
CREATE INDEX IF NOT EXISTS idx_orders_snack_id      ON orders (snack_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer_phone ON orders (customer_phone);
CREATE INDEX IF NOT EXISTS idx_orders_created_at    ON orders (created_at DESC);

-- Row Level Security
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role only" ON orders
    USING (auth.role() = 'service_role');


-- =============================================================================
-- 3. TABLE : customers
--    Profil CRM de chaque client, isolé par tenant.
--    Remplace la table SQLite 'clients'.
-- =============================================================================

CREATE TABLE IF NOT EXISTS customers (
    -- Clé primaire composite (phone + snack) — un client peut avoir plusieurs restos
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identifiant multi-tenant
    snack_id                TEXT NOT NULL REFERENCES snacks(snack_id) ON DELETE CASCADE,

    -- Numéro client E.164
    phone_e164              TEXT NOT NULL,

    -- Timestamps de contact
    first_contact           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_contact            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Compteur de commandes (incrémenté à chaque ivr_choice = "1")
    total_orders            INTEGER NOT NULL DEFAULT 0,

    -- Préférences libres (ex: "burger,sans oignon")
    preferences             TEXT DEFAULT '',

    -- Éligibilité au remarketing (peut être désactivée manuellement)
    remarketing_eligible    BOOLEAN NOT NULL DEFAULT TRUE,

    -- Unicité : un seul profil par (phone, resto)
    UNIQUE (phone_e164, snack_id)
);

-- Index pour les requêtes de remarketing et de lecture fréquente
CREATE INDEX IF NOT EXISTS idx_customers_snack_id    ON customers (snack_id);
CREATE INDEX IF NOT EXISTS idx_customers_phone       ON customers (phone_e164);
CREATE INDEX IF NOT EXISTS idx_customers_last_contact ON customers (last_contact ASC);

-- Row Level Security
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role only" ON customers
    USING (auth.role() = 'service_role');


-- =============================================================================
-- 4. TABLE : interactions
--    Historique de chaque appel IVR par client.
--    Remplace la table SQLite 'interactions'.
-- =============================================================================

CREATE TABLE IF NOT EXISTS interactions (
    -- Clé primaire
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identifiant multi-tenant
    snack_id            TEXT NOT NULL REFERENCES snacks(snack_id) ON DELETE CASCADE,

    -- Numéro client E.164
    phone_e164          TEXT NOT NULL,

    -- Choix IVR : "1" (Menu) ou "2" (Rappel)
    ivr_choice          TEXT NOT NULL CHECK (ivr_choice IN ('1', '2', 'invalide')),

    -- Statut SMS (ex: "Lien envoyé", "Échec", "N/A")
    sms_status          TEXT DEFAULT 'N/A',

    -- Statut transfert / rappel (ex: "En attente", "N/A")
    transfer_status     TEXT DEFAULT 'N/A',

    -- Timestamp UTC
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour l'historique par client + tenant
CREATE INDEX IF NOT EXISTS idx_interactions_snack_id  ON interactions (snack_id);
CREATE INDEX IF NOT EXISTS idx_interactions_phone     ON interactions (phone_e164);
CREATE INDEX IF NOT EXISTS idx_interactions_created_at ON interactions (created_at DESC);

-- Row Level Security
ALTER TABLE interactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role only" ON interactions
    USING (auth.role() = 'service_role');


-- =============================================================================
-- DONNÉES DE TEST (optionnel — à exécuter séparément en dev)
-- =============================================================================

-- INSERT INTO snacks (snack_id, nom_resto, whatsapp_phone_id, whatsapp_token, menu_url, loyalty_threshold, resto_phone)
-- VALUES (
--     'SNACK_TEST_01',
--     'Le Snack du Coin',
--     'VOTRE_PHONE_NUMBER_ID',
--     'VOTRE_ACCESS_TOKEN',
--     'https://snack-flow.com/menu/snack-test-01',
--     3,
--     '+33600000000'
-- )
-- ON CONFLICT (snack_id) DO NOTHING;


-- =============================================================================
-- VUES UTILES (optionnel)
-- =============================================================================

-- Vue : Résumé par restaurant
CREATE OR REPLACE VIEW v_restaurant_stats AS
SELECT
    s.snack_id,
    s.nom_resto,
    COUNT(DISTINCT c.id)    AS total_customers,
    COALESCE(SUM(c.total_orders), 0) AS total_orders,
    COUNT(DISTINCT CASE
        WHEN i.created_at >= NOW() - INTERVAL '30 days'
        THEN i.phone_e164 END
    )                       AS active_last_30d
FROM snacks s
LEFT JOIN customers     c ON c.snack_id = s.snack_id
LEFT JOIN interactions  i ON i.snack_id = s.snack_id
GROUP BY s.snack_id, s.nom_resto;

-- =============================================================================
-- FIN DU SCRIPT
-- =============================================================================
