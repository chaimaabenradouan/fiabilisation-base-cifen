#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
count_pdf_pages.py
=========================================================================
Compte le nombre de pages de chaque PDF dans le dossier "Rapports"
Structure attendue :
Rapport/
├── Entreprise_A/
│   ├── 2018.pdf
│   ├── 2019.pdf
│   └── 2020.pdf
├── Entreprise_B/
└── ...

Génère un JSON bien structuré :
{
  "Entreprise_A": {
    "2018": {"pages": 45, "file": "2018.pdf"},
    "2019": {"pages": 52, "file": "2019.pdf"},
    ...
  },
  ...
}
=========================================================================
"""
import json
from pathlib import Path
from typing import Dict

try:
    from pypdf import PdfReader
except ImportError:
    print("Installation requise : pip install pypdf")
    exit(1)


def count_pages_in_pdf(pdf_path: Path) -> int:
    """Retourne le nombre de pages d'un PDF."""
    try:
        reader = PdfReader(pdf_path)
        return len(reader.pages)
    except Exception as e:
        print(f"Erreur lecture {pdf_path.name} : {e}")
        return -1


def scan_reports_folder(root_folder: str = "Rapports") -> Dict:
    """Parcourt le dossier Rapports et compte les pages."""
    root = Path(root_folder)
    if not root.exists():
        print(f"Erreur: Le dossier '{root}' n'existe pas.")
        return {}

    reports: Dict = {}

    # Parcourir chaque sous-dossier (entreprise)
    for company_dir in sorted(root.iterdir()):
        if not company_dir.is_dir():
            continue

        company_name = company_dir.name
        reports[company_name] = {}

        # Parcourir les PDFs dans le dossier entreprise
        for pdf_file in sorted(company_dir.glob("*.pdf")):
            year = pdf_file.stem  # nom du fichier sans extension = année
            pages = count_pages_in_pdf(pdf_file)

            reports[company_name][year] = {
                "file": pdf_file.name,
                "pages": pages,
                "full_path": str(pdf_file)
            }

            status = "✅" if pages > 0 else "❌"
            print(f"{status} {company_name} / {year} → {pages} pages")

    return reports


def main():
    print("🔍 Analyse du dossier Rapports...\n")

    data = scan_reports_folder("Rapports")

    # Sauvegarde JSON
    output_file = Path("rapport_pages.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Sauvegarde CSV résumé
    with open("rapport_pages.csv", "w", encoding="utf-8", newline="") as f:
        f.write("entreprise;annee;pages;fichier\n")
        for company, years in data.items():
            for year, info in years.items():
                f.write(f"{company};{year};{info['pages']};{info['file']}\n")

    print("\n" + "="*60)
    print(f"✅ Analyse terminée !")
    print(f"   • JSON détaillé : {output_file.resolve()}")
    print(f"   • CSV résumé   : rapport_pages.csv")
    print("="*60)


if __name__ == "__main__":
    main()