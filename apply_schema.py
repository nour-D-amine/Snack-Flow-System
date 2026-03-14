"""
apply_schema.py — Applique init.sql v3.0 sur Supabase
======================================================
Lit le fichier init.sql et l'exécute sur la base Supabase
via une connexion PostgreSQL directe (psycopg2).

Usage :
    python apply_schema.py

Prérequis :
    pip install psycopg2-binary
    Variables .env : SUPABASE_DB_HOST, SUPABASE_PROJECT_REF, SUPABASE_SERVICE_ROLE_KEY
    (ou SUPABASE_DB_PASSWORD = mot de passe PostgreSQL du projet)

Alternative manuelle :
    1. Ouvrir https://supabase.com/dashboard
    2. Votre projet → SQL Editor → New query
    3. Coller le contenu de init.sql → Run
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SQL_FILE = Path(__file__).parent / "init.sql"


def apply_schema():
    """Applique init.sql sur Supabase via psycopg2."""
    db_host     = os.getenv("SUPABASE_DB_HOST", "")
    project_ref = os.getenv("SUPABASE_PROJECT_REF", "")
    db_password = os.getenv("SUPABASE_DB_PASSWORD", "").strip()

    # Fallback : mot de passe via SUPABASE_SERVICE_ROLE_KEY (non standard, déconseillé)
    if not db_password:
        print(
            "⚠️  SUPABASE_DB_PASSWORD non défini dans .env\n"
            "   Récupérez le mot de passe PostgreSQL dans :\n"
            "   Supabase Dashboard → Settings → Database → Connection string\n"
            "   Puis ajoutez SUPABASE_DB_PASSWORD='votre_mdp' dans .env\n"
        )
        print("─" * 60)
        print("📋 ALTERNATIVE MANUELLE (recommandée) :")
        print("   1. Ouvrez : https://supabase.com/dashboard")
        print(f"   2. Projet : {project_ref or 'votre_projet'}")
        print("   3. SQL Editor → New query")
        print("   4. Collez et exécutez le fichier init.sql")
        print("─" * 60)
        sys.exit(1)

    if not db_host:
        print("❌ SUPABASE_DB_HOST manquant dans .env")
        sys.exit(1)

    sql_content = SQL_FILE.read_text(encoding="utf-8")

    print(f"🔌 Connexion à Supabase PostgreSQL : {db_host}")

    try:
        import psycopg2
    except ImportError:
        print("❌ psycopg2-binary non installé : pip install psycopg2-binary")
        sys.exit(1)

    conn = None
    try:
        conn = psycopg2.connect(
            host=db_host,
            port=5432,
            dbname="postgres",
            user="postgres",
            password=db_password,
            sslmode="require",
        )
        conn.autocommit = True
        cursor = conn.cursor()

        print(f"📄 Exécution de {SQL_FILE.name} ({len(sql_content)} chars)...")
        cursor.execute(sql_content)
        print("✅ Schéma v3.0 appliqué avec succès !")

        # Vérification rapide
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY table_name;"
        )
        tables = [r[0] for r in cursor.fetchall()]
        print(f"📊 Tables disponibles : {tables}")

        cursor.close()

    except Exception as e:
        print(f"❌ Erreur lors de l'application du schéma : {e}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    print("🚀 Snack-Flow — Application du schéma init.sql v3.0")
    print("─" * 60)
    apply_schema()
