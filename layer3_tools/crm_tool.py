"""
Layer 3 — Tools : CRM Client (Snack-Flow Multi-Tenant)
=======================================================
Base de données clients locale (SQLite).
Chaque client est associé à un restaurant_id.

Tables :
  - clients       : profil client (téléphone, préférences, stats)
  - interactions  : historique de chaque appel IVR

Objectif à terme : alimentation d'un moteur de remarketing.
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "snackflow_crm.db"
)


# =============================================================================
# INITIALISATION DE LA BASE
# =============================================================================

def _get_connection() -> sqlite3.Connection:
    """Retourne une connexion SQLite avec le mode Row Factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Accès par nom de colonne
    return conn


def initialize_db():
    """
    Crée les tables si elles n'existent pas (idempotent).
    À appeler au démarrage du système.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    # Table clients
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id       TEXT PRIMARY KEY,
            phone_e164      TEXT NOT NULL,
            restaurant_id   TEXT NOT NULL,
            first_contact   TEXT NOT NULL,
            last_contact    TEXT NOT NULL,
            total_orders    INTEGER DEFAULT 0,
            preferences     TEXT DEFAULT '',
            remarketing_eligible INTEGER DEFAULT 1,
            UNIQUE(phone_e164, restaurant_id)
        )
    """)

    # Table interactions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            interaction_id  TEXT PRIMARY KEY,
            phone_e164      TEXT NOT NULL,
            restaurant_id   TEXT NOT NULL,
            ivr_choice      TEXT NOT NULL,
            sms_status      TEXT DEFAULT 'N/A',
            transfer_status TEXT DEFAULT 'N/A',
            timestamp       TEXT NOT NULL
        )
    """)

    # Index pour les requêtes fréquentes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_clients_restaurant
        ON clients (restaurant_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_interactions_phone_resto
        ON interactions (phone_e164, restaurant_id)
    """)

    conn.commit()
    conn.close()
    print("✅ CRM SQLite initialisé.")


# =============================================================================
# CLIENTS — Upsert & Lecture
# =============================================================================

def upsert_client(phone_e164: str, restaurant_id: str, ivr_choice: str = "") -> dict:
    """
    Crée ou met à jour le profil d'un client.
    - Première fois : crée le client
    - Fois suivantes : met à jour last_contact + total_orders si c'est une commande (choix 1)

    :param phone_e164:     Numéro client E.164.
    :param restaurant_id:  ID du restaurant concerné.
    :param ivr_choice:     Choix IVR ("1" ou "2"), pour comptabiliser les commandes.
    :return:               Profil client mis à jour.
    """
    conn = _get_connection()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    # Génère un ID client unique (phone + resto)
    import hashlib
    client_id = hashlib.md5(f"{phone_e164}_{restaurant_id}".encode()).hexdigest()[:12]

    # Incrémente les commandes si c'est l'option 1 (commande en ligne)
    is_order = "1" in ivr_choice

    try:
        # Tente d'insérer
        cursor.execute("""
            INSERT INTO clients (client_id, phone_e164, restaurant_id, first_contact, last_contact, total_orders)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (client_id, phone_e164, restaurant_id, now, now, 1 if is_order else 0))

        print(f"✅ Nouveau client CRM : {phone_e164} → {restaurant_id}")

    except sqlite3.IntegrityError:
        # Client existant : mise à jour
        if is_order:
            cursor.execute("""
                UPDATE clients
                SET last_contact = ?, total_orders = total_orders + 1
                WHERE phone_e164 = ? AND restaurant_id = ?
            """, (now, phone_e164, restaurant_id))
        else:
            cursor.execute("""
                UPDATE clients
                SET last_contact = ?
                WHERE phone_e164 = ? AND restaurant_id = ?
            """, (now, phone_e164, restaurant_id))

        print(f"✅ Client CRM mis à jour : {phone_e164}")

    conn.commit()

    # Récupère le profil complet
    cursor.execute("""
        SELECT * FROM clients WHERE phone_e164 = ? AND restaurant_id = ?
    """, (phone_e164, restaurant_id))
    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else {}


def get_client(phone_e164: str, restaurant_id: str) -> Optional[dict]:
    """Retourne le profil d'un client, ou None s'il n'existe pas."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM clients WHERE phone_e164 = ? AND restaurant_id = ?
    """, (phone_e164, restaurant_id))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_preferences(phone_e164: str, restaurant_id: str, preferences: str) -> bool:
    """Met à jour les préférences d'un client (ex: 'burger,sans oignon')."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE clients SET preferences = ? WHERE phone_e164 = ? AND restaurant_id = ?
    """, (preferences, phone_e164, restaurant_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


# =============================================================================
# INTERACTIONS — Log
# =============================================================================

def log_interaction(
    phone_e164: str,
    restaurant_id: str,
    ivr_choice: str,
    sms_status: str = "N/A",
    transfer_status: str = "N/A"
) -> str:
    """
    Enregistre une interaction dans la table interactions.

    :return: L'ID de l'interaction créée.
    """
    import hashlib
    now = datetime.now(timezone.utc).isoformat()
    interaction_id = hashlib.md5(f"{phone_e164}_{now}".encode()).hexdigest()[:12]

    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO interactions (interaction_id, phone_e164, restaurant_id, ivr_choice, sms_status, transfer_status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (interaction_id, phone_e164, restaurant_id, ivr_choice, sms_status, transfer_status, now))
    conn.commit()
    conn.close()

    print(f"✅ Interaction CRM enregistrée : {interaction_id}")
    return interaction_id


def get_client_history(phone_e164: str, restaurant_id: str) -> list:
    """Retourne l'historique complet des interactions d'un client."""
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM interactions
        WHERE phone_e164 = ? AND restaurant_id = ?
        ORDER BY timestamp DESC
    """, (phone_e164, restaurant_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =============================================================================
# REMARKETING — Segmentation
# =============================================================================

def get_remarketing_targets(restaurant_id: str, inactive_days: int = 30) -> list:
    """
    Retourne les clients éligibles au remarketing pour un restaurant.
    Critères :
      - total_orders >= 1
      - dernière commande il y a plus de `inactive_days` jours
      - remarketing_eligible = 1

    :param restaurant_id:  ID du restaurant.
    :param inactive_days:  Seuil d'inactivité en jours.
    :return:               Liste de profils clients (triés par last_contact ASC).
    """
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM clients
        WHERE restaurant_id = ?
          AND remarketing_eligible = 1
          AND total_orders >= 1
          AND datetime(last_contact) <= datetime('now', ?)
        ORDER BY last_contact ASC
    """, (restaurant_id, f"-{inactive_days} days"))
    rows = cursor.fetchall()
    conn.close()

    targets = [dict(r) for r in rows]
    print(f"📊 Remarketing '{restaurant_id}' : {len(targets)} client(s) inactif(s) depuis {inactive_days}j")
    return targets


def get_restaurant_stats(restaurant_id: str) -> dict:
    """
    Statistiques globales d'un restaurant.

    :return: Dictionnaire avec total clients, total commandes, clients actifs ce mois.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) as total_clients, SUM(total_orders) as total_orders
        FROM clients WHERE restaurant_id = ?
    """, (restaurant_id,))
    global_stats = dict(cursor.fetchone())

    cursor.execute("""
        SELECT COUNT(DISTINCT phone_e164) as active_this_month
        FROM interactions
        WHERE restaurant_id = ?
          AND datetime(timestamp) >= datetime('now', '-30 days')
    """, (restaurant_id,))
    monthly = dict(cursor.fetchone())

    conn.close()
    return {**global_stats, **monthly, "restaurant_id": restaurant_id}


# =============================================================================
# Test standalone
# =============================================================================

if __name__ == "__main__":
    print("--- Test du CRM Tool - Snack-Flow ---\n")
    initialize_db()

    # Simulation d'un client qui commande 2 fois
    test_phone = "+33785557054"
    test_resto = "resto_test"

    print("\n🔄 Première commande...")
    client = upsert_client(test_phone, test_resto, ivr_choice="1")
    print(f"   Profil : {client}")

    print("\n🔄 Deuxième commande...")
    client = upsert_client(test_phone, test_resto, ivr_choice="1")
    print(f"   Total commandes : {client.get('total_orders')}")

    print("\n📊 Stats du restaurant :")
    stats = get_restaurant_stats(test_resto)
    print(f"   {stats}")

    print("\n🎯 Targets remarketing (0 jours = tous) :")
    targets = get_remarketing_targets(test_resto, inactive_days=0)
    print(f"   {len(targets)} client(s) ciblé(s)")
