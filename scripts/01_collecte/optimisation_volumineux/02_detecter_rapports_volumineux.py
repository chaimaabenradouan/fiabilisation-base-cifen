#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_volumineux_from_json.py
=========================================================================
Analyse le fichier rapport_pages.json déjà généré
et détecte les rapports volumineux (≥ 20 pages par défaut)
=========================================================================
"""
import json
from pathlib import Path
from typing import Dict


# ===================== CONFIGURATION =====================
SEUIL_VOLUMINEUX = 20          # ← Change ici le seuil (ex: 30, 40...)
JSON_INPUT = "rapport_pages.json"
# ========================================================


def load_json_data(json_file: str) -> Dict:
    """Charge le JSON généré par count_pdf_pages.py"""
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Fichier {json_file} non trouvé.")
        print("Veuillez d'abord exécuter count_pdf_pages.py")
        exit(1)
    except Exception as e:
        print(f"Erreur lecture JSON : {e}")
        exit(1)


def detect_voluminous_from_json(data: Dict):
    """Détecte les rapports volumineux à partir du JSON"""
    voluminous = {}
    all_count = 0
    vol_count = 0

    print(f"🔍 Analyse du JSON (seuil = {SEUIL_VOLUMINEUX} pages)...\n")

    for company, years in data.items():
        company_vol = []

        for year, info in years.items():
            pages = info.get("pages", 0)
            all_count += 1

            if pages >= SEUIL_VOLUMINEUX:
                vol_count += 1
                company_vol.append({
                    "annee": year,
                    "pages": pages,
                    "fichier": info.get("file", "")
                })
                print(f"📚 VOLUMINEUX | {company:30} | {year:6} | {pages:3} pages")

        if company_vol:
            voluminous[company] = company_vol

    # Résumé
    print("\n" + "="*70)
    print("📊 RÉSUMÉ")
    print("="*70)
    print(f"Total rapports analysés   : {all_count}")
    if all_count > 0:
        print(f"Rapports volumineux       : {vol_count} ({(vol_count/all_count)*100:.1f}%)")
    else:
        print(f"Rapports volumineux       : {vol_count} (0.0%)")
    print(f"Seuil utilisé             : {SEUIL_VOLUMINEUX} pages")
    print("="*70)

    # Sauvegarde résultat
    result = {
        "seuil": SEUIL_VOLUMINEUX,
        "total_rapports": all_count,
        "total_volumineux": vol_count,
        "rapports_volumineux": voluminous
    }

    output_file = Path("rapports_volumineux.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ Résultat sauvegardé dans : {output_file}")
    return voluminous


def main():
    data = load_json_data(JSON_INPUT)
    detect_voluminous_from_json(data)


if __name__ == "__main__":
    main()