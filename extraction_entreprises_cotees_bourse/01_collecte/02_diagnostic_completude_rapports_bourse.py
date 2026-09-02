"""
OMTPME - CIFEN
Analyse des Années Manquantes basée sur le système de fichiers
Source de vérité : le dossier Rapports/
"""

import pandas as pd
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# ====================== CONFIGURATION ======================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT_DIR = PROJECT_ROOT / "Rapports"
OUTPUT_CSV = PROJECT_ROOT / "annees_manquantes.csv"

EXPECTED_YEARS = list(range(2016, 2026))  # 2016 à 2025 inclus

print(f"🔍 Analyse du dossier {ROOT_DIR} en cours...\n")

if not ROOT_DIR.exists():
    raise FileNotFoundError(f"Le dossier attendu n'existe pas : {ROOT_DIR}")

# ====================== PARCOURS DU DOSSIER ======================
company_data = defaultdict(list)

for company_dir in ROOT_DIR.iterdir():
    if not company_dir.is_dir():
        continue
    
    company_name = company_dir.name.replace("_", " ")
    
    for pdf_file in company_dir.glob("**/*.pdf"):
        try:
            # Extraction de l'année depuis le nom du fichier
            year_str = pdf_file.stem.strip()
            year = int(year_str)
            
            if year in EXPECTED_YEARS:
                company_data[company_name].append(year)
        except ValueError:
            # Ignorer les fichiers dont le nom n'est pas une année valide
            continue

# ====================== ANALYSE ======================
results = []

for company_name, years_list in company_data.items():
    years_present = sorted(set(years_list))  # Suppression doublons
    missing_years = [y for y in EXPECTED_YEARS if y not in years_present]
    
    nb_rapports = len(years_present)
    nb_manquants = len(missing_years)
    annees_manquantes_str = ", ".join(map(str, missing_years)) if missing_years else ""
    
    results.append({
        "Nom": company_name,
        "Nb_Rapports": nb_rapports,
        "Nb_Annees_Manquantes": nb_manquants,
        "Annees_Manquantes": annees_manquantes_str
    })

# ====================== CRÉATION DU CSV ======================
df_result = pd.DataFrame(results)
df_result = df_result.sort_values(['Nb_Annees_Manquantes', 'Nom'], ascending=[False, True])


def save_csv_with_fallback(df: pd.DataFrame, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
    try:
        df.to_csv(temp_path, index=False, encoding='utf-8')
        temp_path.replace(output_path)
        return output_path
    except PermissionError as exc:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        fallback_path = output_path.with_name(f"{output_path.stem}_{timestamp}{output_path.suffix}")
        df.to_csv(fallback_path, index=False, encoding='utf-8')
        print(f"⚠️  Permission refusée pour {output_path}, écriture sur {fallback_path} à la place.")
        return fallback_path


OUTPUT_CSV = save_csv_with_fallback(df_result, OUTPUT_CSV)

print(f"✅ Fichier généré : {OUTPUT_CSV}")
print(f"Nombre d'entreprises analysées : {len(df_result)}")

# ====================== RÉSUMÉ CONSOLE ======================
print("\n" + "="*70)
print("📊 RÉSUMÉ DE L'ANALYSE")
print("="*70)

total_companies = len(df_result)
total_reports = df_result['Nb_Rapports'].sum()
total_missing = df_result['Nb_Annees_Manquantes'].sum()

print(f"Nombre d'entreprises analysées     : {total_companies}")
print(f"Nombre total de rapports trouvés   : {total_reports}")
print(f"Nombre total d'années manquantes   : {total_missing}")

if total_companies > 0:
    most_complete = df_result.iloc[-1]
    least_complete = df_result.iloc[0]
    
    print(f"\n🏆 Entreprise la plus complète : {most_complete['Nom']} ({most_complete['Nb_Rapports']}/10)")
    print(f"📉 Entreprise la moins complète: {least_complete['Nom']} ({least_complete['Nb_Rapports']}/10)")

print(f"\nFichier de contrôle prêt : {OUTPUT_CSV}")