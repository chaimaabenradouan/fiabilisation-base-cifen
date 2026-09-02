"""
Phase 2 - Constitution Base Documentaire OMTPME
Scraper Professionnel Rapports Financiers Annuels - Bourse de Casablanca

"""

import time
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
from tqdm import tqdm
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ====================== CONFIGURATION ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.FileHandler("phase2_scraping.log", encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.casablanca-bourse.com"
LISTING_URL = f"{BASE_URL}/fr/listing-des-emetteurs"
START_YEAR = 2016
CURRENT_YEAR = 2026
DATA_DIR = Path("Rapports")
CSV_METADATA = Path("rapports_metadata.csv")
CSV_EMETTEURS = Path("liste_emetteurs.csv")

# Scoring des documents (pondération intelligente)
DOCUMENT_SCORING = {
    "rapport annuel": 100,
    "rapport financier annuel": 98,
    "rfa": 95,
    "document de référence": 92,
    "comptes annuels": 90,
    "états financiers": 88,
    "états de synthèse": 85,
    "rapport de gestion": 80,
    "rapport consolidé": 75,
    "annual report": 70,
    "résultats annuels": 65,
}

KEYWORDS = list(DOCUMENT_SCORING.keys())

# ====================== FONCTIONS UTILES ======================
def clean_filename(text: str) -> str:
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    return re.sub(r'\s+', "_", text.strip())[:120]

def setup_browser():
    """Configuration robuste du navigateur"""
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False, slow_mo=400)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    page = context.new_page()
    return playwright, browser, page

def score_document(title: str) -> Tuple[int, str]:
    """Scoring intelligent d'un document"""
    title_lower = title.lower()
    best_score = 0
    best_type = "inconnu"
    
    for kw, score in DOCUMENT_SCORING.items():
        if kw in title_lower:
            if score > best_score:
                best_score = score
                best_type = kw
    return best_score, best_type

# ====================== PIPELINE PRINCIPAL ======================
def get_all_issuers(page) -> pd.DataFrame:
    """Étape 1: Récupérer TOUS les émetteurs avec pagination robuste"""
    logger.info("Étape 1 - Récupération de tous les émetteurs...")
    page.goto(LISTING_URL, wait_until="networkidle", timeout=90000)
    time.sleep(5)

    all_data = []
    seen = set()
    page_num = 1

    while True:
        logger.info(f"Scraping page listing {page_num}")
        time.sleep(3)
        
        soup = BeautifulSoup(page.content(), 'html.parser')
        rows = soup.select("table tbody tr")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2: continue
            link = cells[0].find("a")
            if not link: continue

            name = link.get_text(strip=True).strip()
            if name in seen: continue
            seen.add(name)

            url = BASE_URL + link["href"] if link["href"].startswith("/") else link["href"]
            ticker = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            capital = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            secteur = cells[3].get_text(strip=True) if len(cells) > 3 else ""

            all_data.append({
                "Nom": name, "Ticker": ticker, "Capital": capital,
                "Secteur": secteur, "URL_Fiche": url
            })

        # Pagination
        try:
            next_btn = page.locator("button.rounded-full, a[rel='next'], li.next").filter(has_text=str(page_num + 1)).first
            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click()
                page_num += 1
                time.sleep(4)
            else:
                break
        except:
            break

    df = pd.DataFrame(all_data)
    df.to_csv(CSV_EMETTEURS, index=False, encoding='utf-8')
    logger.info(f"✅ {len(df)} émetteurs uniques sauvegardés")
    return df


def open_publications_section(page, company_url: str):
    """Étape 2: Ouvrir Publications → Consulter"""
    page.goto(company_url, wait_until="networkidle", timeout=60000)
    time.sleep(3)

    for text in ["Publications des émetteurs", "Publications"]:
        try:
            page.locator(f"text={text}").first.click()
            time.sleep(3)
            break
        except:
            continue

    try:
        page.locator("text=Consulter").first.click()
        time.sleep(4)
    except:
        logger.warning(f"Impossible de cliquer 'Consulter' pour {company_url}")


def get_all_publication_pages(page) -> List[Dict]:
    """Étape 3 + 4: Parcourir toutes les pages de publications"""
    docs = []
    page_num = 1
    max_pages = 20

    while page_num <= max_pages:
        logger.info(f"   Page publications {page_num}")
        time.sleep(3)

        soup = BeautifulSoup(page.content(), 'html.parser')
        links = soup.find_all("a", href=re.compile(r'\.pdf$', re.I))

        for link in links:
            title = link.get_text(strip=True) or ""
            pdf_url = link.get("href")
            if not pdf_url or not title: continue
            if pdf_url.startswith("/"): pdf_url = BASE_URL + pdf_url

            score, doc_type = score_document(title)
            if score < 60: continue  # Seuil minimum

            # Extraction année
            year_match = re.search(r'20(\d{2})', title)
            if not year_match: continue
            year = int("20" + year_match.group(1))
            if not (START_YEAR <= year <= CURRENT_YEAR): continue

            docs.append({
                "Titre": title,
                "URL_PDF": pdf_url,
                "Annee": year,
                "Score": score,
                "Type": doc_type
            })

        # Pagination
        try:
            next_btn = page.locator("button.rounded-full").filter(has_text=str(page_num + 1)).first
            if next_btn.count() > 0:
                next_btn.click()
                page_num += 1
                time.sleep(4)
            else:
                break
        except:
            break

    return docs


def select_best_per_year(docs: List[Dict]) -> Dict[int, Dict]:
    """Étape 5: Sélectionner le meilleur rapport par année"""
    best_per_year = {}
    for doc in docs:
        year = doc["Annee"]
        if year not in best_per_year or doc["Score"] > best_per_year[year]["Score"]:
            best_per_year[year] = doc
    return best_per_year


def download_pdf(page, pdf_url: str, save_path: Path) -> bool:
    """Téléchargement robuste"""
    if save_path.exists():
        return True
    try:
        response = page.request.get(pdf_url, timeout=60000, ignore_https_errors=True)
        if response.status == 200:
            save_path.write_bytes(response.body())
            return True
    except Exception as e:
        logger.error(f"Download failed {pdf_url}: {e}")
    return False


def main():
    """Pipeline complet Phase 2"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    playwright, browser, page = setup_browser()

    try:
        # Étape 1
        issuers_df = get_all_issuers(page)

        all_metadata = []

        for _, issuer in tqdm(issuers_df.iterrows(), total=len(issuers_df), desc="Traitement entreprises"):
            company_name = issuer["Nom"]
            company_dir = DATA_DIR / clean_filename(company_name)
            company_dir.mkdir(parents=True, exist_ok=True)

            try:
                open_publications_section(page, issuer["URL_Fiche"])
                raw_docs = get_all_publication_pages(page)
                best_docs = select_best_per_year(raw_docs)

                for year, doc in best_docs.items():
                    filename = f"{year}.pdf"
                    pdf_path = company_dir / filename

                    if download_pdf(page, doc["URL_PDF"], pdf_path):
                        metadata = {
                            "Nom": company_name,
                            "Ticker": issuer["Ticker"],
                            "Capital": issuer.get("Capital", ""),
                            "Secteur": issuer.get("Secteur", ""),
                            "Annee": year,
                            "Titre": doc["Titre"],
                            "URL_PDF": doc["URL_PDF"],
                            "Chemin_Local": str(pdf_path),
                            "Date_Scrap": datetime.now().isoformat(),
                            "Score_Confiance": doc["Score"],
                            "Type_Detecte": doc["Type"]
                        }
                        all_metadata.append(metadata)

            except Exception as e:
                logger.error(f"Erreur entreprise {company_name}: {e}")

        # Sauvegarde finale
        if all_metadata:
            df_final = pd.DataFrame(all_metadata)
            df_final.to_csv(CSV_METADATA, index=False, encoding='utf-8')
            logger.info(f"🎉 Phase 2 terminée - {len(df_final)} rapports financiers téléchargés")

    finally:
        browser.close()
        playwright.stop()


if __name__ == "__main__":
    main()