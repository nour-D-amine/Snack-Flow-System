"""
Layer 3 — Tools : Phone Tool (Snack-Flow)
==============================================
Outil de normalisation des numéros de téléphone (Format E.164).
Objectif : S'assurer que WhatsApp Business API reçoit des numéros corrects (ex: +33...).
"""

import re
from typing import Optional

def normalize_e164(phone: str, default_prefix: str = "33") -> str:
    """
    Normalise un numéro au format E.164.
    """
    if not phone:
        return ""

    # Nettoyage : Retire tout sauf chiffres et '+'
    cleaned = re.sub(r"[^\d+]", "", phone)
    if not cleaned:
        return ""

    # Si commence par '00', le remplacer par '+'
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    # Si pas de '+' au début
    if not cleaned.startswith("+"):
        if cleaned.startswith("0"):
            # Ex: 0612345678 -> +33612345678
            cleaned = "+" + default_prefix + cleaned[1:]
        else:
            # Ex: 612345678 -> +33612345678
            cleaned = "+" + default_prefix + cleaned

    return cleaned

def safe_normalize(phone: str, default_prefix: str = "33") -> Optional[str]:
    """
    Version safe (ne lève pas d'erreur, retourne None ou le format d'origine s'il est étrange).
    """
    try:
        norm = normalize_e164(phone, default_prefix)
        return norm if norm else phone
    except Exception:
        return phone
