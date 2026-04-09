-- ============================================================
-- SnackFlow v2.0 - Sécurité & Scaling
-- Migration : Fonction RPC pour checkout atomique
-- Objectif : Empêcher 2 instances backend concourantes
-- de vider 2 fois le même panier et de doubler la commande.
-- À exécuter dans l'éditeur SQL de Supabase
-- ============================================================

CREATE OR REPLACE FUNCTION atomic_checkout_cart(p_phone_e164 text, p_snack_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  v_items jsonb;
BEGIN
  -- Suppression atomique de la ligne panier
  -- On récupère la colonne items si la ligne a effectivement été supprimée
  DELETE FROM carts 
  WHERE phone_e164 = p_phone_e164 AND snack_id = p_snack_id 
  RETURNING items INTO v_items;
  
  -- S'il n'y avait pas de ligne, v_items sera NULL,
  -- l'instance appelante sait qu'un autre processus a déjà validé la commande
  RETURN v_items;
END;
$$;
