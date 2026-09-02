#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify_onepage_quality.py  (ÉTAPE 2)
=========================================================================
Pour chaque PDF d'1 page repéré par find_onepage_reports.py, détermine :

    OK_REEL          : contient vraiment des tableaux financiers (au moins
                        2 des 3 états Bilan Actif / Bilan Passif / CPC
                        détectés avec un score suffisant) -> à garder tel quel
    FAKE_ANNONCE      : motif de communiqué détecté, aucun signal financier
                        -> à re-scraper (étape 3)
    SCANNE_A_VERIFIER : texte quasi vide (scan), impossible à juger par le
                        texte -> image générée pour vérification visuelle
    A_VERIFIER        : signal ambigu (ni clairement vrai, ni clairement
                        faux) -> image générée pour vérification visuelle

Réutilise le même moteur (find_tables() + dictionnaires CGNC pondérés +
matching flou) que localization_engine_v2.py, pour rester cohérent avec
le reste du pipeline.

Usage :
    python classify_onepage_quality.py --input nettoyage_1page/ONEPAGE_REPORTS.csv

Sorties :
    nettoyage_1page/CLASSIFICATION_1PAGE.csv
    nettoyage_1page/A_VERIFIER_VISUELLEMENT/<ENTREPRISE>_<ANNEE>.png
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from moteur_reconnaissance_comptable_cgnc import normalize, score_against_category, CATEGORY_KEYWORDS

DEFAULT_INPUT = Path("nettoyage_1page/ONEPAGE_REPORTS.csv")
DEFAULT_OUT = Path("nettoyage_1page/CLASSIFICATION_1PAGE.csv")
REVIEW_DIR = Path("nettoyage_1page/A_VERIFIER_VISUELLEMENT")

MIN_SCORE_CATEGORY = 15     # score minimum pour considérer une catégorie "trouvée"
MIN_CATEGORIES_REEL = 2     # nb minimum de {bilan_actif, bilan_passif, cpc} pour dire "vrai rapport"
SEUIL_CHARS_SCANNE = 50
RENDER_ZOOM = 2.5

ANNOUNCEMENT_PATTERNS = [
    "disponible sur son site internet", "disponible sur le site internet",
    "est aujourd hui disponible", "veuillez consulter notre site",
    "consultable sur le site", "telechargeable sur",
]


def render_page_png(doc: fitz.Document, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM))
    pix.save(str(out_path))


def classify_one_pdf(pdf_path: Path, entreprise: str, annee: str) -> dict:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        return {"verdict": "ERREUR_LECTURE", "detail": str(exc), "n_chars": None,
                "n_tables": None, "categories_trouvees": "", "image_verification": ""}

    page = doc[0]
    text = page.get_text()
    text_norm = normalize(text)
    n_chars = len(text_norm.strip())

    if n_chars < SEUIL_CHARS_SCANNE:
        img_path = REVIEW_DIR / f"{entreprise}_{annee}.png"
        render_page_png(doc, img_path)
        doc.close()
        return {"verdict": "SCANNE_A_VERIFIER", "detail": f"Texte quasi vide ({n_chars} car.), probable scan",
                "n_chars": n_chars, "n_tables": None, "categories_trouvees": "",
                "image_verification": str(img_path)}

    try:
        n_tables = len(page.find_tables().tables)
    except Exception:
        n_tables = 0

    categories_ok = []
    for cat in ("bilan_actif", "bilan_passif", "cpc"):
        score, matched = score_against_category(text, CATEGORY_KEYWORDS[cat], use_fuzzy=False)
        if score >= MIN_SCORE_CATEGORY:
            categories_ok.append(cat)

    ident_score, _ = score_against_category(text, CATEGORY_KEYWORDS["identification"], use_fuzzy=False)
    has_ident = ident_score >= MIN_SCORE_CATEGORY

    is_announcement = any(pat.replace("'", " ").replace("’", " ") in text_norm for pat in ANNOUNCEMENT_PATTERNS)

    doc_ref = doc  # gardé ouvert au cas où on doive rendre une image plus bas

    if is_announcement and len(categories_ok) == 0:
        doc_ref.close()
        return {"verdict": "FAKE_ANNONCE",
                "detail": f"Motif de communiqué détecté, 0/3 état(s) financier(s) trouvé(s)",
                "n_chars": n_chars, "n_tables": n_tables,
                "categories_trouvees": "", "image_verification": ""}

    if len(categories_ok) >= MIN_CATEGORIES_REEL and n_tables >= 1:
        doc_ref.close()
        cats_str = ", ".join(categories_ok) + (", identification" if has_ident else "")
        return {"verdict": "OK_REEL",
                "detail": f"{len(categories_ok)}/3 état(s) financier(s) + {n_tables} tableau(x) détecté(s)",
                "n_chars": n_chars, "n_tables": n_tables,
                "categories_trouvees": cats_str, "image_verification": ""}

    # Signal ambigu : ni clairement faux, ni assez solide pour être sûr -> vérif visuelle
    img_path = REVIEW_DIR / f"{entreprise}_{annee}.png"
    render_page_png(doc_ref, img_path)
    doc_ref.close()
    cats_str = ", ".join(categories_ok) + (", identification" if has_ident else "")
    return {"verdict": "A_VERIFIER",
            "detail": f"Signal ambigu : {len(categories_ok)}/3 état(s), {n_tables} tableau(x)",
            "n_chars": n_chars, "n_tables": n_tables,
            "categories_trouvees": cats_str, "image_verification": str(img_path)}


def main():
    parser = argparse.ArgumentParser(description="Classifie les PDF d'1 page : OK_REEL / FAKE_ANNONCE / A_VERIFIER.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"❌ Fichier introuvable : {args.input} (lance d'abord find_onepage_reports.py)")
        return

    with open(args.input, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"🔍 Classification de {len(rows)} PDF d'1 page...")

    results = []
    for row in rows:
        entreprise, annee = row["Entreprise"], row["Annee"]
        pdf_path = Path(row["Chemin"])
        analysis = classify_one_pdf(pdf_path, entreprise, annee)
        results.append({"Entreprise": entreprise, "Annee": annee, "Chemin": str(pdf_path), **analysis})
        print(f"   [{analysis['verdict']:<18}] {entreprise} / {annee} - {analysis['detail']}")

    verdict_order = {"FAKE_ANNONCE": 0, "SCANNE_A_VERIFIER": 1, "A_VERIFIER": 2,
                      "ERREUR_LECTURE": 3, "OK_REEL": 4}
    results.sort(key=lambda r: verdict_order.get(r["verdict"], 9))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Entreprise", "Annee", "Chemin", "verdict", "detail", "n_chars",
                  "n_tables", "categories_trouvees", "image_verification"]
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    n_reel = sum(1 for r in results if r["verdict"] == "OK_REEL")
    n_fake = sum(1 for r in results if r["verdict"] == "FAKE_ANNONCE")
    n_scan = sum(1 for r in results if r["verdict"] == "SCANNE_A_VERIFIER")
    n_amb = sum(1 for r in results if r["verdict"] == "A_VERIFIER")
    n_err = sum(1 for r in results if r["verdict"] == "ERREUR_LECTURE")

    print("\n" + "=" * 90)
    print("RÉSUMÉ")
    print(f"  OK_REEL (vrais tableaux, à garder)         : {n_reel}")
    print(f"  FAKE_ANNONCE (confirmé faux, à re-scraper) : {n_fake}")
    print(f"  SCANNE_A_VERIFIER (image générée)          : {n_scan}")
    print(f"  A_VERIFIER (signal ambigu, image générée)  : {n_amb}")
    print(f"  Erreurs de lecture                          : {n_err}")
    print(f"  -> CSV : {args.out.resolve()}")
    if n_scan + n_amb > 0:
        print(f"  -> Images à vérifier : {REVIEW_DIR.resolve()}")
    print("  Prochaine étape : vérifie les images, puis rescrape_fake_onepage.py")
    print("=" * 90)


if __name__ == "__main__":
    main()