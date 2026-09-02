#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smart_scrape_batch.py
=========================================================================
BATCH - traite TOUS les rapports volumineux listés dans un JSON
(ex: rapports_volumineux.json généré par ton analyse MinerU).

Ne modifie JAMAIS Rapports/. Tout sort dans smart_test_output/<ENTREPRISE>/,
prêt à être vérifié manuellement avant remplacement.

Principe :
    Pour chaque entreprise du JSON (ex: "MANAGEM": [{"annee":"2018","pages":330,...}]) :
        1. Résout l'URL de la fiche émetteur via liste_emetteurs.csv
        2. Ouvre la page Publications UNE SEULE FOIS pour cette entreprise
           et scrape TOUTES les années disponibles en une passe
        3. Pour CHAQUE année demandée dans le JSON pour cette entreprise :
           compare le PDF local (déjà dans Rapports/) aux candidats en
           ligne de la même année, garde le plus léger valide
        4. Télécharge le meilleur candidat dans smart_test_output/, sans
           jamais toucher à Rapports/
    Un seul navigateur Playwright est utilisé pour tout le batch (pas un
    par entreprise), avec reprise automatique via un registre JSON en cas
    d'interruption.

Usage :
    python smart_scrape_batch.py --json rapports_volumineux.json

    # Tester sur les 3 premières entreprises seulement :
    python smart_scrape_batch.py --json rapports_volumineux.json --limit 3

    # Tester sur UNE entreprise précise :
    python smart_scrape_batch.py --json rapports_volumineux.json --entreprise MANAGEM

    # Reprendre après interruption (ignore les jobs déjà faits) :
    python smart_scrape_batch.py --json rapports_volumineux.json

    # Forcer le retraitement de tout (ignore le registre de reprise) :
    python smart_scrape_batch.py --json rapports_volumineux.json --force

Sorties (tout dans smart_test_output/, RIEN dans Rapports/) :
    smart_test_output/<ENTREPRISE>/<ANNEE>_candidat_leger.pdf
    smart_test_output/<ENTREPRISE>/comparaison_<ENTREPRISE>_<ANNEE>.csv
    smart_test_output/RECAP_GLOBAL.csv          <- à consulter en premier
    smart_test_output/batch_progress.json       <- registre de reprise
    smart_scrape_batch.log
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from tqdm import tqdm

# ====================== CONFIGURATION ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(message)s',
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler("smart_scrape_batch.log", encoding='utf-8'), logging.StreamHandler()],
)
log = logging.getLogger("smart_scrape_batch")

BASE_URL = "https://www.casablanca-bourse.com"
OUTPUT_DIR = Path("smart_test_output")          # <-- dossier SÉPARÉ, jamais Rapports/
DEFAULT_RAPPORTS_DIR = Path("Rapports")
DEFAULT_EMETTEURS_CSV = Path("liste_emetteurs.csv")
PROGRESS_REGISTRY = OUTPUT_DIR / "batch_progress.json"
RECAP_CSV = OUTPUT_DIR / "RECAP_GLOBAL.csv"

DOCUMENT_SCORING = {
    "rapport annuel": 100,
    "rapport financier annuel": 98,
    "rfa": 95,
    "document de référence": 92,
    "comptes annuels": 90,
    "états financiers": 88,
    "etats financiers": 88,
    "états de synthèse": 85,
    "etats de synthese": 85,
    "rapport de gestion": 80,
    "rapport consolidé": 75,
    "rapport consolide": 75,
    "comptes sociaux": 75,
    "annual report": 70,
    "résultats annuels": 65,
    "resultats annuels": 65,
}
DEFAULT_MIN_SCORE = 60


# ====================== STRUCTURES ======================
@dataclass
class DocCandidate:
    titre: str
    url_pdf: Optional[str]
    annee: Optional[int]
    score: int
    type_detecte: str
    nb_pages: Optional[int] = None
    taille_octets: Optional[int] = None
    erreur: Optional[str] = None
    est_local: bool = False


@dataclass
class RecapRow:
    entreprise: str
    annee: str
    pages_local: Optional[int] = None
    pages_candidat: Optional[int] = None
    gain_pages: Optional[int] = None
    statut: str = "non_traite"          # deja_optimal / candidat_telecharge / erreur / non_trouve
    titre_candidat: str = ""
    fichier_sortie: str = ""


# ====================== FONCTIONS UTILES (reprises de smart_scrape_test.py) ======================
def clean_filename(text: str) -> str:
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    return re.sub(r'\s+', "_", text.strip())[:120]


def score_document(title: str) -> tuple[int, str]:
    title_lower = title.lower()
    best_score, best_type = 0, "inconnu"
    for kw, score in DOCUMENT_SCORING.items():
        if kw in title_lower and score > best_score:
            best_score, best_type = score, kw
    return best_score, best_type


def extract_year(title: str) -> Optional[int]:
    matches = re.findall(r'20\d{2}', title)
    return int(matches[-1]) if matches else None


def normalize_name(text: str) -> str:
    if not text:
        return ""
    text = text.replace("_", " ")
    text = text.lower()
    text = re.sub(r'[àáâãäå]', 'a', text)
    text = re.sub(r'[èéêë]', 'e', text)
    text = re.sub(r'[ìíîï]', 'i', text)
    text = re.sub(r'[òóôõö]', 'o', text)
    text = re.sub(r'[ùúûü]', 'u', text)
    text = re.sub(r'ç', 'c', text)
    text = re.sub(r"['’]", "", text)
    text = re.sub(r'[^a-z0-9\s]', "", text)
    text = re.sub(r'\s+', " ", text).strip()
    return text


def find_company_url(company_folder_name: str, emetteurs_rows: list[dict]) -> Optional[str]:
    """Version batch : reçoit les lignes du CSV déjà chargées une fois
    (pas de rechargement disque à chaque entreprise)."""
    target_norm = normalize_name(company_folder_name)

    for row in emetteurs_rows:
        nom = row.get("Nom", "")
        if normalize_name(nom) == target_norm:
            url = row.get("URL_Fiche", "").strip()
            if url:
                return url

    for row in emetteurs_rows:
        nom = row.get("Nom", "")
        nom_norm = normalize_name(nom)
        if target_norm in nom_norm or nom_norm in target_norm:
            url = row.get("URL_Fiche", "").strip()
            if url:
                return url

    return None


def load_emetteurs_csv(path: Path) -> list[dict]:
    if not path.exists():
        log.error(f"liste_emetteurs.csv introuvable à {path} — impossible de résoudre les URLs.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ====================== PLAYWRIGHT ======================
def setup_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False, slow_mo=250)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    page = context.new_page()
    return playwright, browser, page


def open_publications_section(page, company_url: str):
    page.goto(company_url, wait_until="networkidle", timeout=90000)
    time.sleep(2.5)
    for text in ["Publications des émetteurs", "Publications"]:
        try:
            page.locator(f"text={text}").first.click()
            time.sleep(2.5)
            break
        except Exception:
            continue
    try:
        page.locator("text=Consulter").first.click()
        time.sleep(3.5)
    except Exception:
        log.warning("Impossible de cliquer sur 'Consulter'.")


def click_next_publications_page(page, current_page_num: int) -> bool:
    """Pagination robuste (gère aussi les '...' si le site les utilise ici) —
    même logique que generate_emetteurs.py, adaptée à ce composant."""
    next_num = str(current_page_num + 1)

    direct_btn = page.locator(f"button.rounded-full:text-is('{next_num}'), button:text-is('{next_num}')").first
    if direct_btn.count() > 0 and direct_btn.is_visible():
        direct_btn.click()
        return True

    next_arrow = page.locator(
        "button[aria-label*='uivant'], a[aria-label*='uivant'], "
        "button[aria-label*='ext'], a[aria-label*='ext'], "
        "button:has-text('»'), a:has-text('»'), button:has-text('›'), a:has-text('›')"
    ).first
    if next_arrow.count() > 0 and next_arrow.is_visible():
        classes = next_arrow.get_attribute("class") or ""
        if "disabled" not in classes and next_arrow.get_attribute("disabled") is None:
            next_arrow.click()
            return True

    ellipsis = page.locator("button:text-is('...'), a:text-is('...'), span:text-is('...')").first
    if ellipsis.count() > 0 and ellipsis.is_visible():
        ellipsis.click()
        time.sleep(1)
        revealed = page.locator(f"button:text-is('{next_num}'), a:text-is('{next_num}')").first
        if revealed.count() > 0:
            revealed.click()
            return True

    return False


def collect_all_documents_for_company(page) -> list[DocCandidate]:
    """Scrape TOUTES les pages de publications UNE FOIS, toutes années
    confondues (pas de filtre année ici — filtré ensuite en local)."""
    docs: list[DocCandidate] = []
    seen_urls = set()
    page_num = 1
    max_pages = 30
    previous_signature = None

    while page_num <= max_pages:
        time.sleep(2)
        soup = BeautifulSoup(page.content(), 'html.parser')
        links = soup.find_all("a", href=re.compile(r'\.pdf$', re.I))

        page_titles = []
        for link in links:
            title = link.get_text(strip=True) or ""
            pdf_url = link.get("href")
            if not pdf_url or not title:
                continue
            if pdf_url.startswith("/"):
                pdf_url = BASE_URL + pdf_url
            page_titles.append(title)
            if pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)

            score, doc_type = score_document(title)
            year = extract_year(title)
            docs.append(DocCandidate(titre=title, url_pdf=pdf_url, annee=year, score=score, type_detecte=doc_type))

        signature = tuple(sorted(page_titles))
        if previous_signature is not None and signature == previous_signature:
            break  # page bloquée / plus de changement -> on arrête
        previous_signature = signature

        moved = click_next_publications_page(page, page_num)
        if not moved:
            break
        page_num += 1

    return docs


def fetch_pdf_and_count_pages(page, candidate: DocCandidate) -> None:
    try:
        response = page.request.get(candidate.url_pdf, timeout=60000, ignore_https_errors=True)
        if response.status != 200:
            candidate.erreur = f"HTTP {response.status}"
            return
        raw_bytes = response.body()
        candidate.taille_octets = len(raw_bytes)
        with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
            candidate.nb_pages = doc.page_count
    except Exception as exc:
        candidate.erreur = str(exc)


def count_local_pdf_pages(pdf_path: Path) -> Optional[int]:
    try:
        with fitz.open(str(pdf_path)) as doc:
            return doc.page_count
    except Exception:
        return None


def save_comparison_csv(candidates: list[DocCandidate], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Titre", "Type_detecte", "Score", "Nb_pages", "Taille_Ko", "Erreur", "URL_PDF"])
        for c in sorted(candidates, key=lambda x: (x.nb_pages if x.nb_pages is not None else 99999)):
            writer.writerow([
                "LOCAL (déjà dans Rapports/)" if c.est_local else "En ligne",
                c.titre, c.type_detecte, c.score,
                c.nb_pages, round(c.taille_octets / 1024, 1) if c.taille_octets else None,
                c.erreur, c.url_pdf or "-",
            ])


def download_candidate(page, candidate: DocCandidate, dest: Path) -> bool:
    try:
        response = page.request.get(candidate.url_pdf, timeout=60000, ignore_https_errors=True)
        if response.status == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.body())
            return True
    except Exception as exc:
        log.error(f"Échec téléchargement {candidate.url_pdf} : {exc}")
    return False


# ====================== REGISTRE DE REPRISE ======================
def load_progress() -> dict:
    if PROGRESS_REGISTRY.exists():
        try:
            return json.loads(PROGRESS_REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_progress(progress: dict) -> None:
    PROGRESS_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_REGISTRY.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


# ====================== TRAITEMENT D'UNE ENTREPRISE ======================
def process_company(
    page, company: str, entries: list[dict], rapports_dir: Path, out_dir_base: Path,
    emetteurs_rows: list[dict], min_score: int, progress: dict, force: bool,
) -> list[RecapRow]:
    rows: list[RecapRow] = []
    out_dir = out_dir_base / company
    out_dir.mkdir(parents=True, exist_ok=True)

    company_url = find_company_url(company, emetteurs_rows)
    if not company_url:
        log.warning(f"[{company}] URL introuvable dans liste_emetteurs.csv — entreprise ignorée.")
        for e in entries:
            rows.append(RecapRow(entreprise=company, annee=e["annee"], statut="non_trouve"))
        return rows

    try:
        open_publications_section(page, company_url)
        all_docs = collect_all_documents_for_company(page)
    except Exception as exc:
        log.error(f"[{company}] Erreur lors du scraping des publications : {exc}")
        for e in entries:
            rows.append(RecapRow(entreprise=company, annee=e["annee"], statut="erreur"))
        return rows

    docs_by_year: dict[int, list[DocCandidate]] = {}
    for d in all_docs:
        if d.annee is not None and d.score >= min_score:
            docs_by_year.setdefault(d.annee, []).append(d)

    for entry in entries:
        annee = int(entry["annee"])
        job_key = f"{company}/{annee}"

        if not force and progress.get(job_key) == "done":
            continue

        local_pdf = rapports_dir / company / entry["fichier"]
        local_pages = count_local_pdf_pages(local_pdf) if local_pdf.exists() else None

        if local_pages is None:
            log.warning(f"[{company}/{annee}] PDF local introuvable ou illisible : {local_pdf}")
            rows.append(RecapRow(entreprise=company, annee=str(annee), statut="erreur"))
            progress[job_key] = "done"
            continue

        local_candidate = DocCandidate(
            titre=f"[LOCAL] {local_pdf.name}", url_pdf=None, annee=annee,
            score=100, type_detecte="deja_telecharge", nb_pages=local_pages,
            taille_octets=local_pdf.stat().st_size, est_local=True,
        )

        candidates_year = docs_by_year.get(annee, [])
        for c in candidates_year:
            fetch_pdf_and_count_pages(page, c)

        all_candidates = [local_candidate] + candidates_year
        save_comparison_csv(all_candidates, out_dir / f"comparaison_{company}_{annee}.csv")

        valid = [c for c in all_candidates if c.nb_pages is not None]
        best = min(valid, key=lambda c: c.nb_pages) if valid else local_candidate

        if best.est_local:
            rows.append(RecapRow(
                entreprise=company, annee=str(annee), pages_local=local_pages,
                pages_candidat=local_pages, gain_pages=0, statut="deja_optimal",
            ))
        else:
            dest = out_dir / f"{annee}_candidat_leger.pdf"
            ok = download_candidate(page, best, dest)
            if ok:
                rows.append(RecapRow(
                    entreprise=company, annee=str(annee), pages_local=local_pages,
                    pages_candidat=best.nb_pages, gain_pages=local_pages - best.nb_pages,
                    statut="candidat_telecharge", titre_candidat=best.titre,
                    fichier_sortie=str(dest),
                ))
            else:
                rows.append(RecapRow(entreprise=company, annee=str(annee), pages_local=local_pages, statut="erreur"))

        progress[job_key] = "done"
        save_progress(progress)

    return rows


# ====================== RÉCAPITULATIF GLOBAL ======================
def save_recap(all_rows: list[RecapRow], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Entreprise", "Annee", "Pages_locales", "Pages_candidat", "Gain_pages",
                          "Statut", "Titre_candidat", "Fichier_sortie"])
        for r in sorted(all_rows, key=lambda r: (-(r.gain_pages or 0), r.entreprise, r.annee)):
            writer.writerow([r.entreprise, r.annee, r.pages_local, r.pages_candidat, r.gain_pages,
                              r.statut, r.titre_candidat, r.fichier_sortie])
    log.info(f"📊 Récapitulatif global sauvegardé : {out_path.resolve()}")


# ====================== PIPELINE PRINCIPAL ======================
def main():
    parser = argparse.ArgumentParser(description="Batch : optimise tous les rapports volumineux d'un JSON.")
    parser.add_argument("--json", required=True, type=Path, help="Chemin du JSON (ex: rapports_volumineux.json)")
    parser.add_argument("--rapports-dir", type=Path, default=DEFAULT_RAPPORTS_DIR)
    parser.add_argument("--emetteurs-csv", type=Path, default=DEFAULT_EMETTEURS_CSV)
    parser.add_argument("--seuil-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--entreprise", default=None, help="Ne traiter qu'une seule entreprise (test)")
    parser.add_argument("--limit", type=int, default=None, help="Limiter aux N premières entreprises (test)")
    parser.add_argument("--force", action="store_true", help="Ignorer le registre de reprise et tout retraiter")
    args = parser.parse_args()

    data = json.loads(args.json.read_text(encoding="utf-8"))
    rapports = data.get("rapports_volumineux", data)  # tolère un JSON déjà "à plat"

    if args.entreprise:
        rapports = {k: v for k, v in rapports.items() if k == args.entreprise}
    if args.limit:
        rapports = dict(list(rapports.items())[:args.limit])

    if not rapports:
        log.error("Aucune entreprise à traiter (vérifie --entreprise / le contenu du JSON).")
        return

    total_jobs = sum(len(v) for v in rapports.values())
    log.info(f"=== Batch : {len(rapports)} entreprise(s), {total_jobs} rapport(s) à comparer ===")

    emetteurs_rows = load_emetteurs_csv(args.emetteurs_csv)
    progress = {} if args.force else load_progress()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    playwright, browser, page = setup_browser()
    all_rows: list[RecapRow] = []

    try:
        bar = tqdm(rapports.items(), desc="Entreprises", unit="ent")
        for company, entries in bar:
            bar.set_postfix_str(company[:30])
            try:
                rows = process_company(
                    page, company, entries, args.rapports_dir, OUTPUT_DIR,
                    emetteurs_rows, args.seuil_score, progress, args.force,
                )
                all_rows.extend(rows)
            except Exception as exc:
                log.error(f"[{company}] Erreur inattendue, entreprise sautée : {exc}")
                for e in entries:
                    all_rows.append(RecapRow(entreprise=company, annee=e["annee"], statut="erreur"))
    finally:
        browser.close()
        playwright.stop()

    save_recap(all_rows, RECAP_CSV)

    n_optimal = sum(1 for r in all_rows if r.statut == "deja_optimal")
    n_dl = sum(1 for r in all_rows if r.statut == "candidat_telecharge")
    n_err = sum(1 for r in all_rows if r.statut in ("erreur", "non_trouve"))
    gain_total = sum(r.gain_pages or 0 for r in all_rows if r.statut == "candidat_telecharge")

    log.info("=" * 90)
    log.info("RÉSUMÉ DU BATCH")
    log.info(f"  Déjà optimaux (rien à changer)      : {n_optimal}")
    log.info(f"  Candidats plus légers téléchargés   : {n_dl}  (gain total : {gain_total} pages)")
    log.info(f"  Erreurs / non trouvés                : {n_err}")
    log.info(f"  -> Vérifie {RECAP_CSV.resolve()} avant tout remplacement dans Rapports/")
    log.info("=" * 90)


if __name__ == "__main__":
    main()