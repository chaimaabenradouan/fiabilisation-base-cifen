#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify_scanned_vs_text.py
=========================================================================
Classe chaque PDF volumineux en 3 catégories, pour savoir lesquels
peuvent bénéficier du moteur de localisation (texte natif) et lesquels
en sont incapables (scan pur - nécessiterait de l'OCR complet, hors
scope pour l'instant) :

    TEXTE   : texte extractible sur la quasi-totalité des pages
              -> le moteur de localisation peut travailler dessus
    SCANNE  : quasi aucun texte extractible sur la quasi-totalité des
              pages (image pure) -> le moteur de localisation ne peut
              rien faire, il faudra un autre traitement (OCR) plus tard
    MIXTE   : une partie du document est scannée, une autre non (ex:
              annexes scannées mais états financiers en texte natif, ou
              l'inverse) -> à traiter au cas par cas

Critère : proportion de pages "quasi vides" en texte (< 50 caractères
extraits). Rapide (PyMuPDF, pas d'OCR) même sur des PDF de 300+ pages.

Usage :
    python classify_scanned_vs_text.py --json rapports_volumineux.json --seuil-pages 100
    python classify_scanned_vs_text.py --pdf "Rapports/MANAGEM/2018.pdf"   (test sur un seul fichier)

Sortie :
    smart_test_output/CLASSIFICATION_SCAN_TEXTE.csv
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

SEUIL_CHARS_PAGE_VIDE = 50       # en dessous, une page est considérée "vide" en texte
SEUIL_PCT_SCANNE = 0.85          # >= 85% de pages vides -> SCANNE
SEUIL_PCT_TEXTE = 0.15           # <= 15% de pages vides -> TEXTE
DEFAULT_RAPPORTS_DIR = Path("Rapports")
DEFAULT_OUTPUT = Path("smart_test_output/CLASSIFICATION_SCAN_TEXTE.csv")


def classify_pdf(pdf_path: Path) -> dict:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        return {"n_pages": None, "pct_pages_vides": None, "chars_par_page_moyen": None,
                "classification": "ERREUR_LECTURE", "detail": str(exc)}

    n_pages = doc.page_count
    total_chars = 0
    n_pages_vides = 0

    for page in doc:
        text = page.get_text()
        n_chars = len(text.strip())
        total_chars += n_chars
        if n_chars < SEUIL_CHARS_PAGE_VIDE:
            n_pages_vides += 1

    doc.close()

    pct_vides = n_pages_vides / n_pages if n_pages else 1.0
    chars_moyen = total_chars / n_pages if n_pages else 0

    if pct_vides >= SEUIL_PCT_SCANNE:
        classification = "SCANNE"
    elif pct_vides <= SEUIL_PCT_TEXTE:
        classification = "TEXTE"
    else:
        classification = "MIXTE"

    return {
        "n_pages": n_pages,
        "pct_pages_vides": round(pct_vides * 100, 1),
        "chars_par_page_moyen": round(chars_moyen, 1),
        "classification": classification,
        "detail": "",
    }


def main():
    parser = argparse.ArgumentParser(description="Classifie les PDF volumineux en SCANNE / TEXTE / MIXTE.")
    parser.add_argument("--json", type=Path, default=None,
                         help="Chemin du JSON des rapports volumineux (ex: rapports_volumineux.json)")
    parser.add_argument("--pdf", type=Path, default=None,
                         help="Tester sur un seul PDF au lieu d'un JSON complet")
    parser.add_argument("--rapports-dir", type=Path, default=DEFAULT_RAPPORTS_DIR)
    parser.add_argument("--seuil-pages", type=int, default=0,
                         help="Ne traiter que les rapports au-delà de ce nombre de pages "
                              "(0 = tous ceux du JSON, quel que soit le seuil déjà appliqué en amont)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    jobs: list[tuple[str, str, Path]] = []  # (entreprise, annee, pdf_path)

    if args.pdf:
        # Mode test sur un seul fichier : on déduit entreprise/année du chemin si possible
        entreprise = args.pdf.parent.name
        annee = args.pdf.stem
        jobs.append((entreprise, annee, args.pdf))
    elif args.json:
        data = json.loads(args.json.read_text(encoding="utf-8"))
        rapports = data.get("rapports_volumineux", data)
        for entreprise, entries in rapports.items():
            for e in entries:
                if args.seuil_pages and e["pages"] < args.seuil_pages:
                    continue
                pdf_path = args.rapports_dir / entreprise / e["fichier"]
                jobs.append((entreprise, e["annee"], pdf_path))
    else:
        print("❌ Fournis --json ou --pdf")
        return

    print(f"🔍 Classification de {len(jobs)} PDF...")

    results = []
    for entreprise, annee, pdf_path in jobs:
        if not pdf_path.exists():
            results.append({
                "Entreprise": entreprise, "Annee": annee, "Chemin": str(pdf_path),
                "n_pages": None, "pct_pages_vides": None, "chars_par_page_moyen": None,
                "classification": "FICHIER_INTROUVABLE", "detail": "",
            })
            continue

        analysis = classify_pdf(pdf_path)
        results.append({
            "Entreprise": entreprise, "Annee": annee, "Chemin": str(pdf_path),
            **analysis,
        })
        print(f"   [{analysis['classification']:<18}] {entreprise} / {annee} "
              f"({analysis['n_pages']} p., {analysis['pct_pages_vides']}% pages vides)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Entreprise", "Annee", "Chemin", "n_pages", "pct_pages_vides",
                  "chars_par_page_moyen", "classification", "detail"]
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    n_texte = sum(1 for r in results if r["classification"] == "TEXTE")
    n_scanne = sum(1 for r in results if r["classification"] == "SCANNE")
    n_mixte = sum(1 for r in results if r["classification"] == "MIXTE")
    n_err = len(results) - n_texte - n_scanne - n_mixte

    print("\n" + "=" * 90)
    print("RÉSUMÉ")
    print(f"  TEXTE (moteur de localisation exploitable directement) : {n_texte}")
    print(f"  MIXTE (à traiter au cas par cas)                        : {n_mixte}")
    print(f"  SCANNE (nécessite OCR, hors scope pour l'instant)       : {n_scanne}")
    print(f"  Erreurs / introuvables                                   : {n_err}")
    print(f"  -> {args.out.resolve()}")
    print("=" * 90)


if __name__ == "__main__":
    main()