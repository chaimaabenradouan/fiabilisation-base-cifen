#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parcourt toutes les entreprises et extrait le Tableau 3 (Immo. corporelles).
Utilise anchors.py pour trouver y_start dynamiquement par page -- meme
principe que pour le tableau 2, car la hauteur des sections varie d'une
page a l'autre.

FIX (remplace le critere de selection "le plus de champs gagne", qui
choisissait a tort la passe la PLUS POLLUEE -- confirme sur HAO : la passe
x_frac_start=0.35 gagnait avec 4 "champs" trouves, mais 3 d'entre eux
etaient en realite des valeurs du graphique voisin "TITRES FONCIERS CREES"
capturees parce que la boite etait trop large et mordait sur le panneau
d'a cote). extract_table3() calcule deja un score de confiance geometrique
(_diag_avg_score : distance moyenne valeur<->libelle des assignations
retenues -- bas = fiable, eleve = probablement du bruit). On selectionne
desormais la passe avec le MEILLEUR (plus bas) score, le nombre de champs
ne servant plus que de garde-fou minimal (au moins 1 champ trouve).
"""

import json
import csv
import argparse
from pathlib import Path
from PIL import Image
from extraction_entreprises_publiques.scripts.lib.extract_table3 import extract_table3
from extraction_entreprises_publiques.scripts.lib.anchors import find_section_anchors

ENTREPRISES_DIR = Path("../entreprises")
OUTPUT_GLOBAL = Path("../output/toutes_entreprises_table3_v1.csv")

# "Immo. corporelles" est cote a cote avec "Indicateurs d'activite" (a
# gauche). Certaines entreprises (banques : CAM, CDG) ont une mise en page a
# 3 colonnes ou "Terrain & construct." demarre plus a gauche que les grilles
# standard a 4 champs.
X_FRAC_START_CANDIDATES = [0.60, 0.35]


def _extract_best_pass(img, y_start, y_end):
    """
    Essaie chaque largeur candidate, garde celle avec le MEILLEUR score de
    confiance geometrique (_diag_avg_score le plus bas), pas celle avec le
    plus de champs bruts -- voir docstring du module pour le bug HAO que
    l'ancien critere provoquait.
    """
    candidates = []
    for width in X_FRAC_START_CANDIDATES:
        print(f"      (essai x_frac_start={width})")
        result = extract_table3(img, y_start=y_start, y_end=y_end, x_frac_start=width)
        n_fields = len([k for k in result if not k.startswith("_")])
        avg_score = result.get("_diag_avg_score", float("inf"))
        candidates.append((width, result, n_fields, avg_score))
        print(f"      (bilan largeur={width} : {n_fields} champ(s), score={avg_score})")

    valid = [c for c in candidates if c[2] > 0]
    if not valid:
        print("      (aucune passe n'a extrait le moindre champ)")
        return {}

    max_fields = max(c[2] for c in valid)
    # A EGALITE de nombre de champs, prefere la boite la PLUS ETROITE
    # (x_frac_start le plus grand -> boite qui commence le plus a droite,
    # donc moins de risque de mordre sur un graphique voisin) plutot que
    # le score seul. Le score peut etre trompeur : du bruit d'un graphique
    # peut par hasard tomber geometriquement plus pres d'un libelle que la
    # vraie valeur plus bas dans la grille (cas observe sur ONCF : le score
    # de la passe polluee etait meilleur que celui de la passe propre).
    tied_on_max = [c for c in valid if c[2] == max_fields]
    best_width, best_result, best_count, best_score = max(tied_on_max, key=lambda c: c[0])
    print(f"      (retenu: x_frac_start={best_width} avec {best_count} champ(s), score={best_score})")
    return best_result


def process_all(only=None):
    folders = sorted([p for p in ENTREPRISES_DIR.iterdir() if p.is_dir()])

    if only:
        wanted = [o.strip().upper() for o in only]
        folders = [f for f in folders if any(w in f.name.upper() for w in wanted)]
        if not folders:
            print(f"Aucun dossier ne correspond a : {only}")
            return
        print(f"Filtre --only actif : {len(folders)} entreprise(s) selectionnee(s) : "
              f"{[f.name for f in folders]}\n")

    all_results = []

    print(f"Nombre d'entreprises a traiter : {len(folders)}\n")

    for folder in folders:
        page_path = folder / "page.png"
        if not page_path.exists():
            print(f"⚠️  {folder.name} → page.png manquant")
            continue

        print(f"→ Traitement : {folder.name}")

        try:
            img = Image.open(page_path).convert("RGB")

            # ancre dynamique : le tableau 3 va du bandeau "Immo.
            # corporelles" jusqu'au bas de page. Repli sur une fraction
            # fixe UNIQUEMENT si l'ancre manque sur cette page -- pour ne
            # jamais planter.
            anchors = find_section_anchors(img)
            y_start = anchors.get("immo_corporelles", 0.76 * img.height)
            y_end = img.height

            result = _extract_best_pass(img, y_start, y_end)

            if "immo_corporelles" not in anchors:
                result["_warning_ancre"] = "y_start de repli (fraction fixe) - a verifier"

            result["_dossier"] = folder.name

            json_path = folder / "table3_immo_corporelles_v1.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            csv_path = folder / "table3_immo_corporelles_v1.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["champ", "valeur"])
                for k, v in result.items():
                    writer.writerow([k, v])

            all_results.append(result)
            n_fields = len([k for k in result if not k.startswith("_")])
            print(f"   ✅ {n_fields} champs extraits")

        except Exception as e:
            print(f"   ❌ Erreur : {e}")

    if all_results:
        output_path = OUTPUT_GLOBAL
        if only:
            suffix = "_".join(o.strip().upper() for o in only)
            output_path = OUTPUT_GLOBAL.with_name(f"toutes_entreprises_table3_v1_ONLY_{suffix}.csv")

        output_path.parent.mkdir(exist_ok=True, parents=True)
        all_keys = sorted({k for row in all_results for k in row.keys()})

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys)
            writer.writeheader()
            writer.writerows(all_results)

        print(f"\n✅ Terminé.")
        print(f"CSV → {output_path.resolve()}")
    else:
        print("\nAucune donnée extraite.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extrait le Tableau 3 (Immo. corporelles) pour toutes les "
                     "entreprises, ou seulement celles specifiees avec --only."
    )
    parser.add_argument(
        "--only", nargs="+", default=None,
        help="Liste de noms (ou sous-chaines de noms de dossier) a traiter "
             "exclusivement, ex: --only CAM CMR HAO ONMT. Sans cette option, "
             "les 19 entreprises sont traitees (comportement par defaut).",
    )
    args = parser.parse_args()
    process_all(only=args.only)