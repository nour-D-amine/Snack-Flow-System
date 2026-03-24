-- =============================================================================
-- MIGRATION 002 — Ajout colonnes HubRise à la table snacks
-- Supabase Dashboard → SQL Editor → Coller et Run
-- =============================================================================
-- Ajoute les colonnes hubrise_access_token et hubrise_location_id
-- pour stocker les credentials HubRise par tenant (multi-tenant).
-- =============================================================================

-- Étape 1 : Ajouter hubrise_access_token (token OAuth2 obtenu via callback)
ALTER TABLE snacks ADD COLUMN IF NOT EXISTS hubrise_access_token TEXT DEFAULT NULL;

-- Étape 2 : Ajouter hubrise_location_id (ex: "1en7g-0")
ALTER TABLE snacks ADD COLUMN IF NOT EXISTS hubrise_location_id TEXT DEFAULT NULL;

-- Vérification finale
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'snacks'
ORDER BY ordinal_position;
