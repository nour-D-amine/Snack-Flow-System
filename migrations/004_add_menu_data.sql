-- =============================================================================
-- Migration 004 : Ajout du catalogue produit dynamique (menu_data)
-- =============================================================================
-- Permet de stocker le menu JSON directement dans la configuration du snack
-- utilisé par les Skills Gemini (OrderParser, LogicalUpseller) pour
-- valider les commandes et générer les upsells basés sur l'AOV réel.
--
-- Exécuter dans : Supabase Dashboard → SQL Editor → Nouveau script
-- =============================================================================

ALTER TABLE snacks
ADD COLUMN IF NOT EXISTS menu_data JSONB DEFAULT NULL;

-- Exemple pour insérer un catalogue :
-- UPDATE snacks SET menu_data = '{"categories": [{"name": "Burgers", "items": [{"name": "Burger Classique", "price": "8.50 EUR"}, {"name": "Cheeseburger", "price": "10.00 EUR"}]}]}'::jsonb WHERE id = '...';
