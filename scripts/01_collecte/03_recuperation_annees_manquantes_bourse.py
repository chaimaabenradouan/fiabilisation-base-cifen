"""
OMTPME - CIFEN
fill_missing_reports_v5.py

"""

import time
import re
import logging
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import pandas as pd
from tqdm import tqdm
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ===================== CONFIGURATION (Chemins en dur) =====================
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
ARCHIVE_DIR = DATA_DIR / "archive"

OUTPUT_DIR = PROJECT_ROOT / "outputs"
LOG_DIR = PROJECT_ROOT / "logs"
BACKUP_DIR = PROJECT_ROOT / "backup"

METADATA_CSV = DATA_DIR / "rapports_metadata.csv"
EMETTEURS_CSV = DATA_DIR / "liste_emetteurs.csv"
MISSING_CSV_PATTERN = "data/annees_manquantes_*.csv"

# Création des dossiers si nécessaire
for d in [RAW_DIR, INTERIM_DIR, PROCESSED_DIR, ARCHIVE_DIR, OUTPUT_DIR, LOG_DIR, BACKUP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "fill_missing_v5.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.casablanca-bourse.com"
START_YEAR = 2016
CURRENT_YEAR = 2026

# Mots-clés étendus pour détection intelligente
KEYWORDS_ANNUAL = [
    "rapport annuel", "rapport financier annuel", "rfa", "rapport intégré",
    "rapport de gestion", "rapport d'activité", "états financiers",
    "états de synthèse", "comptes annuels", "comptes consolidés",
    "document de référence", "document d'enregistrement universel",
    "communication financière annuelle", "annual report",
    "financial statements", "consolidated financial statements"
]

KEYWORDS_SEMESTRIAL = [
    "rapport semestriel", "rapport financier semestriel", "rapport intermédiaire",
    "états financiers semestriels", "half year", "h1", "h2", "s1", "s2"
]

KEYWORDS_QUARTERLY = [
    "rapport trimestriel", "résultats trimestriels", "q1", "q2", "q3", "q4",
    "t1", "t2", "t3", "t4", "quarterly report"
]

# ====================== FONCTIONS ORIGINALES (intactes) ======================
def clean_filename(text: str) -> str:
    """Nettoie le nom de fichier pour le système de fichiers"""
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    return re.sub(r'\s+', "_", text.strip())[:120]

def setup_browser():
    """Configuration robuste du navigateur"""
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False, slow_mo=400)
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = context.new_page()
    return playwright, browser, page

def score_document(title: str) -> Tuple[int, str]:
    """Scoring intelligent étendu"""
    title_lower = title.lower()
    best_score = 0
    best_type = "inconnu"
    
    # Recherche annuelle
    for kw in KEYWORDS_ANNUAL:
        if kw in title_lower:
            score = 100 - KEYWORDS_ANNUAL.index(kw) * 5
            if score > best_score:
                best_score = score
                best_type = kw
    
    # Recherche semestrielle
    for kw in KEYWORDS_SEMESTRIAL:
        if kw in title_lower and best_score == 0:
            best_score = 70
            best_type = "semestriel"
    
    # Recherche trimestrielle
    for kw in KEYWORDS_QUARTERLY:
        if kw in title_lower and best_score == 0:
            best_score = 50
            best_type = "trimestriel"
    
    return best_score, best_type

def open_publications_section(page, company_url: str):
    """Navigation vers Publications → Consulter"""
    logger.info(f"  → Ouverture fiche : {company_url}")
    page.goto(company_url, wait_until="networkidle", timeout=60000)
    time.sleep(3)
    logger.info("  ✓ Fiche entreprise chargée")

    for text in ["Publications des émetteurs", "Publications"]:
        try:
            page.locator(f"text={text}").first.click()
            time.sleep(3)
            logger.info(f"  ✓ Onglet '{text}' cliqué")
            break
        except:
            continue
    try:
        page.locator("text=Consulter").first.click()
        time.sleep(4)
        logger.info("  ✓ Bouton 'Consulter' cliqué")
    except:
        logger.warning("  ✗ Impossible de cliquer 'Consulter'")

def get_all_publication_pages(page) -> List[Dict]:
    """
    Pagination robuste avec détection intelligente des changements de contenu.
    Version 4.0 - Production Ready
    """
    docs = []
    page_num = 1
    visited_hashes = set()
    max_pages = 100 # Sécurité anti-boucle infinie

    logger.info("  → Début de l'analyse des publications")

    while page_num <= max_pages:
        time.sleep(2) # Petit délai pour laisser le JS se stabiliser

        # Capture du contenu avant clic
        html_before = page.content()
        page_hash = hash(html_before[:5000]) # Hash partiel pour performance

        if page_hash in visited_hashes:
            logger.warning(f"⚠️ Boucle détectée - Page {page_num} semble être un doublon")
            break
        visited_hashes.add(page_hash)

        # Analyse de la page courante
        soup = BeautifulSoup(html_before, 'html.parser')
        links = soup.find_all("a", href=re.compile(r'\.pdf$', re.I))
        
        logger.info(f"    Page {page_num} - {len(links)} PDF détectés")

        # Premier et dernier PDF pour diagnostic
        if links:
            first_title = links[0].get_text(strip=True)[:80]
            last_title = links[-1].get_text(strip=True)[:80]
            logger.info(f"      Premier PDF : {first_title}")
            logger.info(f"      Dernier PDF : {last_title}")

        for link in links:
            title = link.get_text(strip=True) or ""
            pdf_url = link.get("href")
            if not pdf_url or not title: continue
            if pdf_url.startswith("/"): pdf_url = BASE_URL + pdf_url

            score, doc_type = score_document(title)
            year_match = re.search(r'20(\d{2})', title + " " + pdf_url)
            if not year_match: continue
            year = int("20" + year_match.group(1))
            if not (START_YEAR <= year <= CURRENT_YEAR): continue

            docs.append({
                "Titre": title, "URL_PDF": pdf_url, "Annee": year,
                "Score": score, "Type": doc_type
            })

        # Vérification du bouton Suivant
        try:
            next_btn = page.locator("button.rounded-full, a[rel='next'], li.next").first
            if next_btn.count() == 0 or not next_btn.is_visible():
                logger.info("    ✓ Aucune page suivante - Fin de la pagination")
                break

            logger.info(f"    → Clic sur 'Suivant' (page {page_num} → {page_num + 1})")
            
            # Attente intelligente du changement de contenu
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            next_btn.click()

            # Attente robuste du chargement
            page.wait_for_load_state("networkidle", timeout=10000)
            time.sleep(2) # Délai minimum pour stabilisation

            # Vérification que le contenu a changé
            html_after = page.content()
            if hash(html_after[:5000]) == page_hash:
                logger.warning("    ⚠️ Contenu identique après clic - Arrêt de la pagination")
                break

            page_num += 1

        except Exception as e:
            logger.warning(f"    ⚠️ Erreur pagination : {e}")
            break

    logger.info(f"  ✓ Analyse terminée : {page_num-1} pages | {len(docs)} PDF trouvés")
    return docs

def select_best_per_year(docs: List[Dict]):
    """Sélection du meilleur document par année"""
    best = {}
    for doc in docs:
        y = doc["Annee"]
        if y not in best or doc["Score"] > best[y]["Score"]:
            best[y] = doc
    return best

def download_pdf(page, pdf_url: str, save_path: Path) -> bool:
    """Téléchargement robuste et sécurisé"""
    if save_path.exists():
        logger.info(f"   Déjà présent → {save_path.name}")
        return True
    try:
        response = page.request.get(pdf_url, timeout=60000, ignore_https_errors=True)
        if response.status == 200:
            save_path.write_bytes(response.body())
            logger.info(f"   ✅ Téléchargé → {save_path.name}")
            return True
    except Exception as e:
        logger.error(f"Download failed {pdf_url}: {e}")
    return False

# ====================== VERSION 5.0 - RATTRAPAGE INTELLIGENT ======================
def get_latest_missing_csv() -> Path:
    files = list(Path("data").glob("annees_manquantes_*.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier annees_manquantes trouvé")
    return max(files, key=lambda x: x.stat().st_mtime)

def create_backup():
    if METADATA_CSV.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"rapports_metadata_backup_{timestamp}.csv"
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(METADATA_CSV, backup_path)
        logger.info(f"Backup créé : {backup_path.name}")

def main():
    create_backup()

    missing_csv = get_latest_missing_csv()
    df_missing = pd.read_csv(missing_csv)
    df_missing = df_missing[df_missing['Nb_Annees_Manquantes'] > 0].copy()

    if df_missing.empty:
        logger.info("✅ Toutes les entreprises sont complètes !")
        return

    logger.info(f"🔄 Rattrapage Version 5.0 - {len(df_missing)} entreprises incomplètes...")

    emetteurs_file = Path("data/liste_emetteurs.csv")
    if emetteurs_file.exists():
        df_emetteurs = pd.read_csv(emetteurs_file)
        url_map = dict(zip(df_emetteurs['Nom'], df_emetteurs['URL_Fiche']))
    else:
        logger.error("Fichier liste_emetteurs.csv non trouvé")
        return

    playwright, browser, page = setup_browser()
    new_metadata = []
    followup = []

    try:
        for _, row in tqdm(df_missing.iterrows(), total=len(df_missing), desc="Rattrapage V5"):
            company_name = row['Nom']
            missing_str = str(row.get('Annees_Manquantes', '')).strip()
            missing_years = [int(y.strip()) for y in missing_str.split(',') if y.strip()]

            company_dir = RAW_DIR / clean_filename(company_name)
            company_url = url_map.get(company_name)
            if not company_url:
                logger.warning(f"URL non trouvée pour {company_name}")
                followup.append({"Nom": company_name, "Statut": "URL introuvable"})
                continue

            logger.info(f"Traitement {company_name} | Années : {missing_years}")

            try:
                open_publications_section(page, company_url)
                raw_docs = get_all_publication_pages(page)
                best_docs = select_best_per_year(raw_docs)

                for year in missing_years:
                    if year in best_docs:
                        doc = best_docs[year]
                        pdf_path = company_dir / f"{year}.pdf"

                        if download_pdf(page, doc["URL_PDF"], pdf_path):
                            new_metadata.append({
                                "Nom": company_name,
                                "Ticker": row.get("Ticker", ""),
                                "Capital": row.get("Capital", ""),
                                "Secteur": row.get("Secteur", ""),
                                "Annee": year,
                                "Titre": doc["Titre"],
                                "URL_PDF": doc["URL_PDF"],
                                "Chemin_Local": str(pdf_path),
                                "Date_Scrap": datetime.now().isoformat(),
                                "Score_Confiance": doc["Score"],
                                "Type_Detecte": doc["Type"]
                            })
                            followup.append({
                                "Nom": company_name,
                                "Annee": year,
                                "Statut": "Succès",
                                "Titre": doc["Titre"]
                            })
                    else:
                        followup.append({
                            "Nom": company_name,
                            "Annee": year,
                            "Statut": "Introuvable",
                            "Titre": ""
                        })
            except Exception as e:
                logger.error(f"Erreur {company_name}: {e}")
                followup.append({"Nom": company_name, "Statut": f"Erreur: {str(e)[:100]}"})

    finally:
        browser.close()
        playwright.stop()

    # Mise à jour metadata
    if new_metadata:
        new_df = pd.DataFrame(new_metadata)
        if METADATA_CSV.exists():
            existing = pd.read_csv(METADATA_CSV)
            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=['Chemin_Local'])
            combined.to_csv(METADATA_CSV, index=False, encoding='utf-8')
        else:
            new_df.to_csv(METADATA_CSV, index=False, encoding='utf-8')

        logger.info(f"✅ {len(new_metadata)} nouveaux rapports ajoutés")

    # Sauvegarde followup
    if followup:
        pd.DataFrame(followup).to_csv("data/rapports_recuperes.csv", index=False, encoding='utf-8')

    # Relancer vérification
    logger.info("🔄 Relancement de la vérification des années manquantes...")
    # subprocess.run(["python", "anneemanquant.py"])

    logger.info("🎉 Rattrapage Version 5.0 terminé")

if __name__ == "__main__":
    main()