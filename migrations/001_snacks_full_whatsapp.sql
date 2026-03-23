-- ==========================================================================
-- SnackFlow v2.0 — Migration : snacks table (Full-WhatsApp Schema)
-- ==========================================================================
-- Fichier  : migrations/001_snacks_full_whatsapp.sql
-- Projet   : SnackFlow (api.menudirect.fr)
-- Date     : 2026-03-23
-- Objectif : S'assurer que la table `snacks` contient toutes les colonnes
--            requises pour l'architecture 100% WhatsApp via Meta API.
-- ==========================================================================

-- Activation de l'extension UUID si nécessaire
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================================================
-- Création de la table snacks (si elle n'existe pas)
-- ==========================================================================

CREATE TABLE IF NOT EXISTS public.snacks (
    id                       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                     TEXT        NOT NULL,
    phone_number_id          TEXT        UNIQUE NOT NULL,  -- Meta phone_number_id
    menu_url                 TEXT,
    loyalty_threshold        INT         NOT NULL DEFAULT 5,
    is_active                BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==========================================================================
-- Ajout des colonnes manquantes (idempotent — ALTER TABLE IF NOT EXISTS)
-- ==========================================================================

-- Colonne : phone_number_id (renommée depuis whatsapp_phone_number_id si besoin)
DO $$
BEGIN
    -- Ajoute phone_number_id si absente
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'snacks'
          AND column_name  = 'phone_number_id'
    ) THEN
        -- Vérifie si l'ancienne colonne whatsapp_phone_number_id existe pour la renommer
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name   = 'snacks'
              AND column_name  = 'whatsapp_phone_number_id'
        ) THEN
            ALTER TABLE public.snacks
                RENAME COLUMN whatsapp_phone_number_id TO phone_number_id;
            RAISE NOTICE 'Colonne renommée : whatsapp_phone_number_id → phone_number_id';
        ELSE
            ALTER TABLE public.snacks
                ADD COLUMN phone_number_id TEXT UNIQUE;
            RAISE NOTICE 'Colonne ajoutée : phone_number_id';
        END IF;
    END IF;

    -- menu_url
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'snacks'
          AND column_name  = 'menu_url'
    ) THEN
        ALTER TABLE public.snacks ADD COLUMN menu_url TEXT;
        RAISE NOTICE 'Colonne ajoutée : menu_url';
    END IF;

    -- loyalty_threshold
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'snacks'
          AND column_name  = 'loyalty_threshold'
    ) THEN
        ALTER TABLE public.snacks ADD COLUMN loyalty_threshold INT NOT NULL DEFAULT 5;
        RAISE NOTICE 'Colonne ajoutée : loyalty_threshold';
    END IF;

    -- is_active
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'snacks'
          AND column_name  = 'is_active'
    ) THEN
        ALTER TABLE public.snacks ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
        RAISE NOTICE 'Colonne ajoutée : is_active';
    END IF;

    -- updated_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'snacks'
          AND column_name  = 'updated_at'
    ) THEN
        ALTER TABLE public.snacks ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        RAISE NOTICE 'Colonne ajoutée : updated_at';
    END IF;
END $$;

-- ==========================================================================
-- Index de performance
-- ==========================================================================

CREATE UNIQUE INDEX IF NOT EXISTS snacks_phone_number_id_idx
    ON public.snacks (phone_number_id);

CREATE INDEX IF NOT EXISTS snacks_is_active_idx
    ON public.snacks (is_active);

-- ==========================================================================
-- Trigger : updated_at automatique
-- ==========================================================================

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS snacks_updated_at ON public.snacks;
CREATE TRIGGER snacks_updated_at
    BEFORE UPDATE ON public.snacks
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ==========================================================================
-- Row Level Security (RLS) — Multi-Tenant
-- ==========================================================================

ALTER TABLE public.snacks ENABLE ROW LEVEL SECURITY;

-- Politique : le service_role (backend) a accès total
DROP POLICY IF EXISTS snacks_service_role_all ON public.snacks;
CREATE POLICY snacks_service_role_all ON public.snacks
    AS PERMISSIVE FOR ALL
    TO service_role
    USING (TRUE)
    WITH CHECK (TRUE);

-- ==========================================================================
-- Schéma final attendu de la table snacks
-- ==========================================================================
-- COLUMN               TYPE        NULLABLE  DEFAULT            NOTES
-- id                   UUID        NOT NULL  gen_random_uuid()  PK
-- name                 TEXT        NOT NULL  —                  Nom du restaurant
-- phone_number_id      TEXT        NOT NULL  —                  Meta phone_number_id (UNIQUE)
-- menu_url             TEXT        NULL      —                  URL du menu interactif
-- loyalty_threshold    INT         NOT NULL  5                  Nb commandes seuil fidélité
-- is_active            BOOLEAN     NOT NULL  TRUE               Soft-delete
-- created_at           TIMESTAMPTZ NOT NULL  NOW()
-- updated_at           TIMESTAMPTZ NOT NULL  NOW()              Auto-updated via trigger
-- ==========================================================================
