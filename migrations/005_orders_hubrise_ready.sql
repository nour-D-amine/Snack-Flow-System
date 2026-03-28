-- =============================================================================
-- MIGRATION 005 — Liaison HubRise + statut "ready" sur la table orders
-- Supabase Dashboard → SQL Editor → Coller et Run
-- =============================================================================
-- 1. Ajoute hubrise_order_id TEXT (lien entre commande interne et commande HubRise)
-- 2. Met à jour la contrainte CHECK sur status pour inclure 'ready'
-- =============================================================================

-- Étape 1 : Ajouter la colonne hubrise_order_id (nullable, UNIQUE pour éviter les doublons)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS hubrise_order_id TEXT DEFAULT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_hubrise_order_id
    ON orders (hubrise_order_id)
    WHERE hubrise_order_id IS NOT NULL;

-- Étape 2 : Mettre à jour la contrainte CHECK sur status pour inclure 'ready'
-- PostgreSQL ne supporte pas ALTER CONSTRAINT — on doit la recréer.
DO $$
DECLARE
    v_constraint_name text;
BEGIN
    SELECT conname INTO v_constraint_name
    FROM pg_constraint
    WHERE conrelid = 'orders'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%status%';

    IF v_constraint_name IS NOT NULL THEN
        EXECUTE 'ALTER TABLE orders DROP CONSTRAINT ' || quote_ident(v_constraint_name);
        RAISE NOTICE 'Contrainte % supprimée.', v_constraint_name;
    ELSE
        RAISE NOTICE 'Aucune contrainte CHECK sur status trouvée — ajout direct.';
    END IF;
END;
$$;

ALTER TABLE orders
    ADD CONSTRAINT orders_status_check
    CHECK (status IN ('pending', 'confirmed', 'ready', 'failed', 'cancelled'));

-- Vérification finale
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'orders'
ORDER BY ordinal_position;
