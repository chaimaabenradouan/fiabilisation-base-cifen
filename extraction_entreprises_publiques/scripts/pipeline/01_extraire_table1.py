#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parcourt toutes les entreprises et extrait le Tableau 1 (Informations de
base). Utilise anchors.py pour trouver y_end dynamiquement par page (au
lieu d'une fraction fixe de la hauteur) -- indispensable car la hauteur
du bandeau nom-entreprise varie d'une page a l'autre (1 a 3 lignes).
"""

import json
import csv
from pathlib import Path
from PIL import Image
from extraction_entreprises_publiques.scripts.lib.extract_table1 import extract_table1
from extraction_entreprises_publiques.scripts.lib.anchors import find_section_anchors

ENTREPRISES_DIR = Path("../entreprises")
OUTPUT_GLOBAL = Path("../output/toutes_entreprises_table1_v1.csv")


def process_all():
    folders = sorted([p for p in ENTREPRISES_DIR.iterdir() if p.is_dir()])
    all_results = []

    print(f"Nombre d'entreprises trouvées : {len(folders)}\n")

    for folder in folders:
        page_path = folder / "page.png"
        if not page_path.exists():
            print(f"⚠️  {folder.name} → page.png manquant")
            continue

        print(f"→ Traitement : {folder.name}")

        try:
            img = Image.open(page_path).convert("RGB")

            # ancre dynamique : fin du tableau 1 = debut du bandeau
            # "Indicateurs économiques et financiers". Repli sur 0.40*h
            # (comportement precedent) UNIQUEMENT si l'ancre n'est pas
            # trouvee sur cette page -- pour ne jamais planter.
            anchors = find_section_anchors(img)
            y_end = anchors.get("indicateurs_financiers", 0.40 * img.height)

            result = extract_table1(
                img,
                y_start=0,          # extract_table1 relocalise SIGLE en interne
                y_end=y_end,
                x_frac_end=None,
            )
            if "indicateurs_financiers" not in anchors:
                result["_warning_ancre"] = "y_end de repli (fraction fixe) - a verifier"

            # repli : le nom de dossier commence deja par le sigle
            # (convention observee : "ADM_GROUPE_..." etc.) -- mieux
            # qu'un champ vide si l'OCR n'a rien trouve du tout
            if not result.get("sigle"):
                result["sigle"] = folder.name.split("_")[0] + " (a verifier)"

            result["_dossier"] = folder.name

            json_path = folder / "table1_infos_v1.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            csv_path = folder / "table1_infos_v1.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["champ", "valeur"])
                for k, v in result.items():
                    writer.writerow([k, v])

            all_results.append(result)
            print(f"   ✅ {len([v for v in result.values() if v])} champs extraits")

        except Exception as e:
            print(f"   ❌ Erreur : {e}")

    if all_results:
        OUTPUT_GLOBAL.parent.mkdir(exist_ok=True, parents=True)
        all_keys = sorted({k for row in all_results for k in row.keys()})

        with open(OUTPUT_GLOBAL, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys)
            writer.writeheader()
            writer.writerows(all_results)

        print(f"\n✅ Terminé.")
        print(f"CSV global → {OUTPUT_GLOBAL.resolve()}")
    else:
        print("\nAucune donnée extraite.")


if __name__ == "__main__":
    process_all()