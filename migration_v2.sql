-- =============================================================================
-- MIGRATION v2.0 — Table interactions
-- Supabase Dashboard → SQL Editor → Coller et Run
-- =============================================================================
-- Renomme les colonnes IVR → colonnes WhatsApp
-- et met à jour les contraintes CHECK.
-- =============================================================================

-- Étape 1 : Supprimer les contraintes CHECK obsolètes sur ivr_choice
ALTER TABLE interactions DROP CONSTRAINT IF EXISTS interactions_ivr_choice_check;
ALTER TABLE interactions DROP CONSTRAINT IF EXISTS interactions_sms_status_check;
ALTER TABLE interactions DROP CONSTRAINT IF EXISTS interactions_transfer_status_check;

-- Étape 2 : Renommer ivr_choice → wa_direction
ALTER TABLE interactions RENAME COLUMN ivr_choice TO wa_direction;

-- Étape 3 : Renommer sms_status → wa_type
ALTER TABLE interactions RENAME COLUMN sms_status TO wa_type;

-- Étape 4 : Renommer transfer_status → wa_status
ALTER TABLE interactions RENAME COLUMN transfer_status TO wa_status;

-- Étape 5 : Ajouter la colonne message_preview
ALTER TABLE interactions ADD COLUMN IF NOT EXISTS message_preview TEXT DEFAULT '';

-- Étape 6 : Ajouter les nouvelles contraintes CHECK
ALTER TABLE interactions
    ADD CONSTRAINT interactions_wa_direction_check
    CHECK (wa_direction IN ('inbound', 'outbound'));

ALTER TABLE interactions
    ADD CONSTRAINT interactions_wa_type_check
    CHECK (wa_type IN ('order', 'confirmation', 'kitchen_ticket', 'remarketing', 'other'));

ALTER TABLE interactions
    ADD CONSTRAINT interactions_wa_status_check
    CHECK (wa_status IN ('Envoyé', 'Échec', 'En attente'));

-- Étape 7 : Mettre à jour les valeurs existantes (compatibilité)
UPDATE interactions SET wa_direction = 'inbound'  WHERE wa_direction NOT IN ('inbound', 'outbound');
UPDATE interactions SET wa_type      = 'order'     WHERE wa_type NOT IN ('order', 'confirmation', 'kitchen_ticket', 'remarketing', 'other');
UPDATE interactions SET wa_status    = 'En attente' WHERE wa_status NOT IN ('Envoyé', 'Échec', 'En attente');

-- Étape 8 : Mettre à jour la contrainte CHECK sur orders.status (v3 — valeurs anglaises)
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_status_check;
ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending';
UPDATE orders SET status = 'pending'   WHERE status NOT IN ('pending', 'confirmed', 'failed', 'cancelled');
ALTER TABLE orders ADD CONSTRAINT orders_status_check
    CHECK (status IN ('pending', 'confirmed', 'failed', 'cancelled'));

-- Vérification finale
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'interactions'
ORDER BY ordinal_position;
