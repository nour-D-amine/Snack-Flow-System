-- =============================================================================
-- Snack-Flow — init.sql — Schéma Multi-Tenant SaaS (v4.0)
-- =============================================================================
-- Architecture : Multi-Tenant via snack_id (UUID) — isolation par restaurant
-- Exécuter dans : Supabase Dashboard → SQL Editor → Nouveau script
--
-- Tables :
--   1. snacks     → Tenants (restaurants, credentials WA & HubRise, menu_data)
--   2. orders     → Commandes WhatsApp (JSONB items, isolées par snack_id)
--   3. customers  → CRM clients (fidélité, remarketing)
--   4. carts      → Paniers actifs (un par client × snack, vidé à la validation)
--
-- Fonctions RPC :
--   - atomic_checkout_cart() → DELETE RETURNING atomique pour multi-instances
--
-- Sécurité :
--   - Row Level Security (RLS) activé sur toutes les tables
--   - Toutes les clés sensibles restent dans .env (jamais en base)
--   - Accès serveur via service_role key uniquement
-- =============================================================================

-- ─── Extension UUID ──────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── Nettoyage de l'ancien schéma ───────────────────────────────────────────
DROP TABLE IF EXISTS carts CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS interactions CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS snacks CASCADE;


-- =============================================================================
-- 1. TABLE : snacks
--    Un enregistrement = un restaurant (tenant).
--    Authentification : whatsapp_phone_number_id (envoyé par Meta à chaque webhook).
-- =============================================================================

CREATE TABLE IF NOT EXISTS snacks (
    -- Clé primaire UUID auto-générée
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Nom du restaurant (affiché dans les messages WhatsApp)
    name                        TEXT NOT NULL,

    -- Identifiant du numéro WhatsApp Business (Meta → metadata.phone_number_id)
    -- UNIQUE : permet d'authentifier le tenant entrant de façon déterministe
    whatsapp_phone_number_id    TEXT NOT NULL UNIQUE,

    -- Actif/Inactif : un snack inactif est rejeté avec [UNAUTHORIZED_SNACK]
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,

    -- ── HubRise POS Integration ────────────────────────────────────────────
    -- Credentials OAuth2 obtenus via /hubrise/connect → /hubrise/callback
    hubrise_access_token        TEXT DEFAULT '',
    hubrise_location_id         TEXT DEFAULT '',

    -- ── Configuration métier ───────────────────────────────────────────────
    -- URL du menu web (fallback)
    menu_url                    TEXT DEFAULT '',
    -- Seuil de fidélité (nombre de commandes pour remarketing)
    loyalty_threshold           INTEGER DEFAULT 5,
    -- Numéro du gérant (E.164) pour les alertes WhatsApp
    resto_phone                 TEXT DEFAULT '',
    -- Logo du restaurant (URL image pour header menu WhatsApp)
    logo_url                    TEXT DEFAULT '',

    -- ── Catalogue dynamique ────────────────────────────────────────────────
    -- JSONB libre : {"categories": [...]} ou liste plate ou dict de catégories
    -- Clé interne _out_of_stock ajoutée par sync_stock_with_supabase()
    menu_data                   JSONB DEFAULT NULL,

    -- Timestamps UTC
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index de lookup rapide pour l'authentification webhook
CREATE INDEX IF NOT EXISTS idx_snacks_phone_number_id
    ON snacks (whatsapp_phone_number_id);

-- Trigger : mise à jour automatique de updated_at
CREATE OR REPLACE FUNCTION snacks_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_snacks_updated_at ON snacks;
CREATE TRIGGER trg_snacks_updated_at
    BEFORE UPDATE ON snacks
    FOR EACH ROW EXECUTE FUNCTION snacks_set_updated_at();

-- Row Level Security : lecture/écriture uniquement via service_role
ALTER TABLE snacks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "snacks_service_role_only" ON snacks;
CREATE POLICY "snacks_service_role_only" ON snacks
    USING (auth.role() = 'service_role');


-- =============================================================================
-- 2. TABLE : orders
--    Journal des commandes WhatsApp, isolées par tenant (snack_id UUID).
--    items : JSONB — structure libre, ex: [{"name": "Burger", "qty": 2}]
-- =============================================================================

CREATE TABLE IF NOT EXISTS orders (
    -- Clé primaire UUID auto-générée
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- FK vers le tenant (restaurant)
    snack_id        UUID NOT NULL REFERENCES snacks(id) ON DELETE CASCADE,

    -- Numéro client E.164 (ex: "+33785557054")
    customer_phone  TEXT NOT NULL,

    -- Détail des articles commandés (JSONB libre)
    -- Exemple : [{"name": "Burger classique", "qty": 1, "price": 8.50}]
    items           JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Statut de la commande
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'confirmed', 'ready', 'failed', 'cancelled')),

    -- Identifiant HubRise (lié après push_to_hubrise réussi)
    hubrise_order_id TEXT DEFAULT '',

    -- Timestamp UTC de création
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index pour les requêtes fréquentes par tenant
CREATE INDEX IF NOT EXISTS idx_orders_snack_id      ON orders (snack_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer_phone ON orders (customer_phone);
CREATE INDEX IF NOT EXISTS idx_orders_created_at    ON orders (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status        ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_hubrise_id    ON orders (hubrise_order_id);

-- =============================================================================
-- RLS sur orders : isolation complète par tenant (snack_id)
-- =============================================================================

ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

-- Politique service_role : accès total (backend serveur)
DROP POLICY IF EXISTS "orders_service_role_all" ON orders;
CREATE POLICY "orders_service_role_all" ON orders
    USING (auth.role() = 'service_role');

-- Politique tenant : un snack ne voit que ses propres commandes
-- (utile si on expose jamais des JWT anon — défense en profondeur)
DROP POLICY IF EXISTS "orders_tenant_isolation" ON orders;
CREATE POLICY "orders_tenant_isolation" ON orders
    USING (
        snack_id = (
            SELECT id FROM snacks
            WHERE whatsapp_phone_number_id = current_setting('app.current_phone_id', TRUE)
            LIMIT 1
        )
    );


-- =============================================================================
-- 3. TABLE : customers
--    Profils clients CRM mis à jour à chaque message WhatsApp pour le tenant.
-- =============================================================================

CREATE TABLE IF NOT EXISTS customers (
    -- Clé primaire UUID
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identifiant multi-tenant (UUID FK vers snacks)
    snack_id                UUID NOT NULL REFERENCES snacks(id) ON DELETE CASCADE,

    -- Numéro client E.164
    phone_e164              TEXT NOT NULL,

    -- Timestamps de contact
    first_contact           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_contact            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Compteur de commandes validées (incrémenté uniquement à la validation)
    total_orders            INTEGER NOT NULL DEFAULT 0,

    -- Préférences libres (ex: "burger,sans oignon")
    preferences             TEXT DEFAULT '',

    -- Éligibilité au remarketing
    remarketing_eligible    BOOLEAN NOT NULL DEFAULT FALSE,

    -- Unicité : un seul profil par (phone, tenant)
    UNIQUE (phone_e164, snack_id)
);

-- Index pour les requêtes CRM
CREATE INDEX IF NOT EXISTS idx_customers_snack_id    ON customers (snack_id);
CREATE INDEX IF NOT EXISTS idx_customers_phone       ON customers (phone_e164);
CREATE INDEX IF NOT EXISTS idx_customers_last_contact ON customers (last_contact ASC);

-- Row Level Security
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "customers_service_role_only" ON customers;
CREATE POLICY "customers_service_role_only" ON customers
    USING (auth.role() = 'service_role');


-- =============================================================================
-- 4. TABLE : carts
--    Paniers actifs clients — une ligne par (client, snack).
--    Vidé après validation de commande (DELETE atomique via RPC).
-- =============================================================================

CREATE TABLE IF NOT EXISTS carts (
    phone_e164   TEXT          NOT NULL,
    snack_id     UUID          NOT NULL REFERENCES snacks(id) ON DELETE CASCADE,
    items        JSONB         NOT NULL DEFAULT '[]',
    total_price  NUMERIC(10,2) NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (phone_e164, snack_id)
);

COMMENT ON TABLE carts IS 'Paniers actifs clients — une ligne par (client, snack). Vidé après validation de commande.';
COMMENT ON COLUMN carts.phone_e164  IS 'Numéro client au format E.164 (ex: +33785557054)';
COMMENT ON COLUMN carts.snack_id    IS 'UUID du restaurant (FK snacks.id)';
COMMENT ON COLUMN carts.items       IS 'Liste JSONB : [{"id":str,"name":str,"price":float,"qty":int}]';
COMMENT ON COLUMN carts.total_price IS 'Total calculé côté serveur (somme price*qty)';
COMMENT ON COLUMN carts.updated_at  IS 'Mis à jour automatiquement par trigger';

-- Index pour accès rapide par numéro client
CREATE INDEX IF NOT EXISTS idx_carts_phone ON carts(phone_e164);

-- Trigger updated_at automatique
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS carts_updated_at ON carts;
CREATE TRIGGER carts_updated_at
    BEFORE UPDATE ON carts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Row Level Security
ALTER TABLE carts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_only" ON carts
    USING (auth.role() = 'service_role');


-- =============================================================================
-- 5. FONCTION RPC : atomic_checkout_cart
--    DELETE RETURNING atomique pour empêcher les doublons multi-instances.
-- =============================================================================

CREATE OR REPLACE FUNCTION atomic_checkout_cart(p_phone_e164 text, p_snack_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  v_items jsonb;
BEGIN
  DELETE FROM carts
  WHERE phone_e164 = p_phone_e164 AND snack_id = p_snack_id
  RETURNING items INTO v_items;

  RETURN v_items;
END;
$$;


-- =============================================================================
-- DONNÉES DE TEST — Snack exemple (désactivé par défaut)
-- =============================================================================
-- Décommentez et adaptez pour insérer un tenant de test :
--
-- INSERT INTO snacks (name, whatsapp_phone_number_id, is_active)
-- VALUES ('Snack Demo Paris', '123456789012345', TRUE)
-- ON CONFLICT (whatsapp_phone_number_id) DO NOTHING;


-- =============================================================================
-- FIN DU SCRIPT init.sql v4.0
-- =============================================================================
