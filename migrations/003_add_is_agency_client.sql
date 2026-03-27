-- =============================================================================
-- MIGRATION 003 — Ajout colonne is_agency_client à la table snacks
-- Distingue les clients SaaS (base) des clients Agence (premium/remarketing IA)
-- =============================================================================

-- Étape 1 : Ajout de la colonne (FALSE par défaut → offre SaaS de base)
ALTER TABLE snacks
ADD COLUMN IF NOT EXISTS is_agency_client BOOLEAN NOT NULL DEFAULT FALSE;

-- Étape 2 : Commentaire descriptif sur la colonne
COMMENT ON COLUMN snacks.is_agency_client IS 'Définit si le snack a souscrit à l''offre Agence de Remarketing';
