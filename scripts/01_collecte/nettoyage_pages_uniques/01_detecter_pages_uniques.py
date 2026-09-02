#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_onepage_reports.py  (ÉTAPE 1)
=========================================================================
Scanne TOUT le dossier Rapports/ (toutes entreprises, toutes années — pas
seulement les rapports volumineux) et repère les PDF d'UNE SEULE PAGE.
C'est cette catégorie précise qui s'est révélée trompeuse : parfois un
vrai état financier condensé, parfois juste un communiqué renvoyant vers
un site web.

Ne modifie rien dans Rapports/, lecture seule.

Usage :
    python find_onepage_reports.py --rapports-dir Rapports

Sortie :
    nettoyage_1page/ONEPAGE_REPORTS.csv
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import fitz  # PyMuPDF

DEFAULT_RAPPORTS_DIR = Path("Rapports")
DEFAULT_OUT = Path("nettoyage_1page/ONEPAGE_REPORTS.csv")


def main():
    parser = argparse.ArgumentParser(description="Repère tous les PDF d'1 page dans Rapports/.")
    parser.add_argument("--rapports-dir", type=Path, default=DEFAULT_RAPPORTS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    pdf_paths = sorted(args.rapports_dir.glob("*/*.pdf"))
    print(f"🔍 Scan de {len(pdf_paths)} PDF dans {args.rapports_dir}...")

    results = []
    n_erreurs = 0

    for pdf_path in pdf_paths:
        entreprise = pdf_path.parent.name
        annee = pdf_path.stem
        try:
            with fitz.open(str(pdf_path)) as doc:
                n_pages = doc.page_count
        except Exception as exc:
            print(f"   ❌ Erreur lecture {pdf_path} : {exc}")
            n_erreurs += 1
            continue

        if n_pages == 1:
            taille_ko = round(pdf_path.stat().st_size / 1024, 1)
            results.append({
                "Entreprise": entreprise, "Annee": annee,
                "Chemin": str(pdf_path), "Taille_Ko": taille_ko,
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["Entreprise", "Annee", "Chemin", "Taille_Ko"])
        writer.writeheader()
        writer.writerows(results)

    print("\n" + "=" * 90)
    print(f"RÉSUMÉ")
    print(f"  Total PDF scannés          : {len(pdf_paths)}")
    print(f"  PDF d'une seule page trouvés : {len(results)}")
    print(f"  Erreurs de lecture          : {n_erreurs}")
    print(f"  -> {args.out.resolve()}")
    print("  Prochaine étape : classify_onepage_quality.py")
    print("=" * 90)


if __name__ == "__main__":
    main()