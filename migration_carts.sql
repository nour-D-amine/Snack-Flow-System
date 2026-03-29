-- ============================================================
-- SnackFlow v3.1 — Migration : table carts
-- À exécuter dans l'éditeur SQL de Supabase
-- ============================================================

-- 1. Création de la table
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

-- 2. Index pour accès rapide par numéro client
CREATE INDEX IF NOT EXISTS idx_carts_phone ON carts(phone_e164);

-- 3. Trigger updated_at automatique
--    (La fonction update_updated_at peut déjà exister sur d'autres tables)
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

-- 4. Row Level Security (recommandé pour Supabase)
--    Le service_role bypasse le RLS — le code serveur est sûr.
ALTER TABLE carts ENABLE ROW LEVEL SECURITY;

-- Politique : lecture/écriture uniquement via service_role (côté serveur)
-- Aucun accès anon ou authenticated direct (tout passe par le webhook Flask)
CREATE POLICY "service_role_only" ON carts
    USING (auth.role() = 'service_role');
