#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rescrape_fake_onepage.py  (v2 - vérification de contenu, pas de règle aveugle)
=========================================================================
CORRECTIFS par rapport à la v1 :

    1. v1 filtrait les candidats par leur TITRE (DOCUMENT_SCORING), ce qui
       a raté des documents valides au titre atypique (ex: "Avis de
       convocation à l'AGO" contenant en fait les comptes annuels, mais
       aucun mot du dictionnaire dans le titre). v2 collecte TOUS les
       documents de l'année, sans filtre de titre : le CONTENU décide.

    2. v1 excluait systématiquement tout candidat d'1 page, ce qui était
       trop radical : un candidat 1 page en ligne peut être un vrai état
       financier condensé, différent du faux que tu as en local. v2
       analyse le contenu réel de CHAQUE candidat (détection de tableaux +
       mots-clés CGNC, comme classify_onepage_quality.py) et choisit le
       minimum de pages PARMI CEUX CONFIRMÉS RÉELS, qu'ils fassent 1 page
       ou 300.

Ne touche JAMAIS à Rapports/. Tout sort dans nettoyage_1page/.

Usage :
    python rescrape_fake_onepage.py --classification RESCRAPE_TARGETS.csv --verdicts FAKE_ANNONCE SCANNE_A_VERIFIER A_VERIFIER

Sorties :
    nettoyage_1page/<ENTREPRISE>/comparaison_<ENTREPRISE>_<ANNEE>.csv   (tous les candidats + leur verdict qualité)
    nettoyage_1page/<ENTREPRISE>/<ANNEE>_candidat_leger.pdf              (le meilleur candidat réel, si trouvé)
    nettoyage_1page/RESCRAPE_REPORT.csv
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts.nettoyage_pages_uniques.moteur_reconnaissance_comptable_cgnc import normalize, score_against_category, CATEGORY_KEYWORDS  # noqa: E402

BASE_URL = "https://www.casablanca-bourse.com"
OUTPUT_DIR = Path("nettoyage_1page")
DEFAULT_EMETTEURS_CSV = Path("liste_emetteurs.csv")

MIN_SCORE_CATEGORY = 15
MIN_CATEGORIES_REEL = 2
MAX_PAGES_FOR_TABLE_CHECK = 15   # au-delà, on ne relance pas find_tables() sur chaque page (coûteux, peu utile)

ANNOUNCEMENT_PATTERNS = [
    "disponible sur son site internet", "disponible sur le site internet",
    "est aujourd hui disponible", "veuillez consulter notre site",
    "consultable sur le site", "telechargeable sur",
]


@dataclass
class DocCandidate:
    titre: str
    url_pdf: str
    annee: Optional[int]
    nb_pages: Optional[int] = None
    taille_octets: Optional[int] = None
    erreur: Optional[str] = None
    verdict: str = ""
    detail: str = ""
    categories_trouvees: str = ""


def normalize_name(text: str) -> str:
    if not text:
        return ""
    text = text.replace("_", " ").lower()
    for accented, plain in [("àáâãäå", "a"), ("èéêë", "e"), ("ìíîï", "i"), ("òóôõö", "o"), ("ùúûü", "u")]:
        for ch in accented:
            text = text.replace(ch, plain)
    text = text.replace("ç", "c").replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_company_url(company_folder_name: str, emetteurs_csv: Path) -> Optional[str]:
    if not emetteurs_csv.exists():
        return None
    with open(emetteurs_csv, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    target = normalize_name(company_folder_name)
    for row in rows:
        if normalize_name(row.get("Nom", "")) == target:
            return row.get("URL_Fiche", "").strip() or None
    for row in rows:
        nom_norm = normalize_name(row.get("Nom", ""))
        if target in nom_norm or nom_norm in target:
            return row.get("URL_Fiche", "").strip() or None
    return None


def extract_year(title: str) -> Optional[int]:
    matches = re.findall(r"20\d{2}", title)
    return int(matches[-1]) if matches else None


def setup_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False, slow_mo=250)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    return playwright, browser, context.new_page()


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
        pass


def collect_documents_for_year(page, target_year: int) -> list[DocCandidate]:
    """AUCUN filtre de titre ici : on ramène TOUT ce qui correspond à
    l'année, le contenu décidera ensuite ce qui est exploitable."""
    docs, seen_urls = [], set()
    page_num, max_pages = 1, 30
    while page_num <= max_pages:
        time.sleep(2)
        soup = BeautifulSoup(page.content(), "html.parser")
        for link in soup.find_all("a", href=re.compile(r"\.pdf$", re.I)):
            title = link.get_text(strip=True) or ""
            pdf_url = link.get("href")
            if not pdf_url or not title:
                continue
            if pdf_url.startswith("/"):
                pdf_url = BASE_URL + pdf_url
            if pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)
            year = extract_year(title)
            if year != target_year:
                continue
            docs.append(DocCandidate(titre=title, url_pdf=pdf_url, annee=year))
        try:
            next_btn = page.locator("button.rounded-full").filter(has_text=str(page_num + 1)).first
            if next_btn.count() > 0:
                next_btn.click()
                page_num += 1
                time.sleep(3)
            else:
                break
        except Exception:
            break
    return docs


def analyze_pdf_bytes(raw_bytes: bytes) -> tuple[int, str, str, str]:
    """Retourne (n_pages, verdict, detail, categories_trouvees) à partir du
    contenu réel du PDF (mêmes règles que classify_onepage_quality.py)."""
    doc = fitz.open(stream=raw_bytes, filetype="pdf")
    n_pages = doc.page_count

    full_text = ""
    n_tables = 0
    check_tables = n_pages <= MAX_PAGES_FOR_TABLE_CHECK
    for p in doc:
        full_text += p.get_text()
        if check_tables:
            try:
                n_tables += len(p.find_tables().tables)
            except Exception:
                pass
    doc.close()

    text_norm = normalize(full_text)
    categories_ok = []
    for cat in ("bilan_actif", "bilan_passif", "cpc"):
        score, _ = score_against_category(full_text, CATEGORY_KEYWORDS[cat], use_fuzzy=False)
        if score >= MIN_SCORE_CATEGORY:
            categories_ok.append(cat)

    is_announcement = any(normalize(p) in text_norm for p in ANNOUNCEMENT_PATTERNS)
    cats_str = ", ".join(categories_ok)

    if is_announcement and len(categories_ok) == 0:
        return n_pages, "FAKE_ANNONCE", "Motif de communiqué, aucun état financier détecté", cats_str

    # Pour les documents longs (pas de vérif de tableaux), on exige un
    # signal texte un peu plus large pour compenser l'absence de check
    # structurel, mais reste beaucoup plus permissif que l'ancienne
    # exclusion aveugle des 1-page.
    if len(categories_ok) >= MIN_CATEGORIES_REEL and (not check_tables or n_tables >= 1):
        return n_pages, "OK_REEL", f"{len(categories_ok)}/3 état(s) financier(s), {n_tables if check_tables else '?'} tableau(x)", cats_str

    return n_pages, "A_VERIFIER", f"Signal insuffisant : {len(categories_ok)}/3 état(s)", cats_str


def fetch_and_analyze(page, candidate: DocCandidate) -> None:
    try:
        response = page.request.get(candidate.url_pdf, timeout=60000, ignore_https_errors=True)
        if response.status != 200:
            candidate.erreur = f"HTTP {response.status}"
            return
        raw = response.body()
        candidate.taille_octets = len(raw)
        n_pages, verdict, detail, cats = analyze_pdf_bytes(raw)
        candidate.nb_pages = n_pages
        candidate.verdict = verdict
        candidate.detail = detail
        candidate.categories_trouvees = cats
    except Exception as exc:
        candidate.erreur = str(exc)


def save_comparison_csv(candidates: list[DocCandidate], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Titre", "Nb_pages", "Verdict", "Detail", "Categories_trouvees",
                          "Taille_Ko", "Erreur", "URL_PDF"])
        for c in sorted(candidates, key=lambda x: (x.nb_pages if x.nb_pages is not None else 99999)):
            writer.writerow([c.titre, c.nb_pages, c.verdict, c.detail, c.categories_trouvees,
                              round(c.taille_octets / 1024, 1) if c.taille_octets else None,
                              c.erreur, c.url_pdf])


def download_candidate(page, candidate: DocCandidate, dest: Path) -> bool:
    try:
        response = page.request.get(candidate.url_pdf, timeout=60000, ignore_https_errors=True)
        if response.status == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.body())
            return True
    except Exception:
        pass
    return False


def main():
    parser = argparse.ArgumentParser(description="Re-scrape avec vérification de contenu réel (v2).")
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--emetteurs-csv", type=Path, default=DEFAULT_EMETTEURS_CSV)
    parser.add_argument("--verdicts", nargs="+", default=["FAKE_ANNONCE"])
    args = parser.parse_args()

    with open(args.classification, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    jobs = [r for r in rows if r["verdict"] in args.verdicts]
    print(f"🔍 {len(jobs)} entreprise(s)/année(s) à re-scraper (verdicts: {args.verdicts})...")

    playwright, browser, page = setup_browser()
    results = []

    try:
        for job in jobs:
            entreprise, annee = job["Entreprise"], int(job["Annee"])
            print(f"\n--- {entreprise} / {annee} ---")

            company_url = find_company_url(entreprise, args.emetteurs_csv)
            if not company_url:
                print(f"   ❌ URL introuvable pour {entreprise}")
                results.append({"Entreprise": entreprise, "Annee": annee, "Statut": "URL_INTROUVABLE",
                                 "Pages_candidat": "", "Titre_candidat": "", "Fichier": ""})
                continue

            try:
                open_publications_section(page, company_url)
                docs = collect_documents_for_year(page, annee)
            except Exception as exc:
                print(f"   ❌ Erreur scraping : {exc}")
                results.append({"Entreprise": entreprise, "Annee": annee, "Statut": "ERREUR_SCRAPING",
                                 "Pages_candidat": "", "Titre_candidat": "", "Fichier": ""})
                continue

            if not docs:
                print(f"   — Aucun document trouvé pour cette année sur le site.")
                results.append({"Entreprise": entreprise, "Annee": annee, "Statut": "AUCUN_DOCUMENT_EN_LIGNE",
                                 "Pages_candidat": "", "Titre_candidat": "", "Fichier": ""})
                continue

            for d in docs:
                fetch_and_analyze(page, d)
                print(f"   [{d.verdict or 'ERREUR':<12}] '{d.titre[:55]}' -> {d.nb_pages} pages - {d.detail or d.erreur}")

            out_dir = OUTPUT_DIR / entreprise
            save_comparison_csv(docs, out_dir / f"comparaison_{entreprise}_{annee}.csv")

            real_candidates = [d for d in docs if d.verdict == "OK_REEL" and d.nb_pages is not None]

            if not real_candidates:
                print(f"   — Aucun candidat confirmé réel (contenu vérifié).")
                results.append({"Entreprise": entreprise, "Annee": annee, "Statut": "AUCUN_CANDIDAT_FIABLE",
                                 "Pages_candidat": "", "Titre_candidat": "", "Fichier": ""})
                continue

            best = min(real_candidates, key=lambda d: d.nb_pages)
            dest = out_dir / f"{annee}_candidat_leger.pdf"
            if download_candidate(page, best, dest):
                print(f"   ✅ Retenu : '{best.titre[:60]}' ({best.nb_pages} pages, contenu vérifié) -> {dest}")
                results.append({"Entreprise": entreprise, "Annee": annee, "Statut": "CANDIDAT_TROUVE",
                                 "Pages_candidat": best.nb_pages, "Titre_candidat": best.titre, "Fichier": str(dest)})
            else:
                results.append({"Entreprise": entreprise, "Annee": annee, "Statut": "ECHEC_TELECHARGEMENT",
                                 "Pages_candidat": "", "Titre_candidat": "", "Fichier": ""})
    finally:
        browser.close()
        playwright.stop()

    report_path = OUTPUT_DIR / "RESCRAPE_REPORT.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["Entreprise", "Annee", "Statut", "Pages_candidat",
                                                 "Titre_candidat", "Fichier"])
        writer.writeheader()
        writer.writerows(results)

    n_ok = sum(1 for r in results if r["Statut"] == "CANDIDAT_TROUVE")
    print("\n" + "=" * 90)
    print(f"RÉSUMÉ : {n_ok} candidat(s) fiable(s) trouvé(s) et vérifié(s) sur {len(jobs)}.")
    print(f"-> {report_path.resolve()}")
    print("Rien n'a été modifié dans Rapports/. Vérifie les comparaison_*.csv avant tout remplacement.")
    print("=" * 90)


if __name__ == "__main__":
    main()