import gspread
import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

SPREADSHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_FILE = "service_account.json"
SERVICE_EMAIL = "snack-flow-bot@snack-flow-automation.iam.gserviceaccount.com"

def test_google_sheets_connection():
    print("--- Test de Connexion Google Sheets pour Snack-Flow ---")
    
    # 1. Vérifier la présence du fichier JSON
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"❌ ERREUR : Le fichier {SERVICE_ACCOUNT_FILE} est introuvable à la racine.")
        return

    # 2. Vérifier que l'ID de la Sheet est présent
    if not SPREADSHEET_ID or SPREADSHEET_ID == "your_google_sheet_id_here":
        print(f"❌ ERREUR : GOOGLE_SHEET_ID n'est pas configuré correctement dans le fichier .env.")
        print(f"-> Veuillez créer un fichier .env (en copiant .env.template) et y ajouter l'ID de votre Sheet.")
        return

    try:
        print(f"🔄 Authentification avec le Service Account ({SERVICE_EMAIL})...")
        gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        
        print(f"🔄 Ouverture du document Google Sheet ID : {SPREADSHEET_ID[:10]}...")
        sh = gc.open_by_key(SPREADSHEET_ID)
        
        # Essayer de lire la première page (worksheet)
        worksheet = sh.sheet1
        valeurs = worksheet.get_all_values()
        
        print("✅ SUCCÈS ! Connexion établie avec Google Sheets.")
        print(f"📌 Titre du Document : {sh.title}")
        print(f"📌 Nombre de lignes dans la première feuille : {len(valeurs)}")
        
    except gspread.exceptions.SpreadsheetNotFound:
        print("❌ ERREUR : Document introuvable.")
        print(f"-> Avez-vous pensé à PARTAGER le Google Sheet avec l'adresse e-mail suivante (en mode Lecteur ou Éditeur) ?\n   {SERVICE_EMAIL}")
    except Exception as e:
        print(f"❌ ERREUR inattendue : {e}")

if __name__ == "__main__":
    test_google_sheets_connection()
