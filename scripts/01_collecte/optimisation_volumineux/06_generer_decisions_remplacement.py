#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_replacement_decisions.py
=========================================================================
Combine :
    - QUALITY_CHECK.csv (verdicts automatiques : OK_MULTIPAGE, OK_AUTO,
      A_VERIFIER, SUSPECT_ANNONCE, erreurs)
    - overrides.csv (tes décisions manuelles après vérification visuelle
      des images dans A_VERIFIER_VISUELLEMENT/, qui ont priorité absolue
      sur le verdict automatique)

Produit REPLACEMENT_DECISIONS.csv : une ligne par candidat, avec une
colonne 'Action' = "remplacer" ou "garder_original".

RÈGLES PAR DÉFAUT (si pas d'override) :
    OK_MULTIPAGE                    -> remplacer   (validé manuellement : >1 page = fiable)
    OK_AUTO                         -> remplacer   (tableau + mots-clés détectés)
    A_VERIFIER                      -> garder_original (par prudence : la plupart se sont
                                                          révélés être des faux lors de ta
                                                          vérification manuelle)
    SUSPECT_ANNONCE                 -> garder_original (communiqué vide confirmé)
    FICHIER_INTROUVABLE / ERREUR_LECTURE -> garder_original (rien d'exploitable)

Ce script NE TOUCHE À AUCUN FICHIER PDF. Il ne fait que produire un CSV
de décisions, que tu peux encore relire/éditer à la main avant d'exécuter
apply_replacements.py.

Usage :
    python generate_replacement_decisions.py

    # Avec des chemins personnalisés :
    python generate_replacement_decisions.py --quality smart_test_output/QUALITY_CHECK.csv --overrides overrides.csv
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

DEFAULT_ACTION_BY_VERDICT = {
    "OK_MULTIPAGE": "remplacer",
    "OK_AUTO": "remplacer",
    "A_VERIFIER": "garder_original",
    "SUSPECT_ANNONCE": "garder_original",
    "FICHIER_INTROUVABLE": "garder_original",
    "ERREUR_LECTURE": "garder_original",
}


def load_overrides(path: Path) -> dict[tuple[str, str], dict]:
    """Charge overrides.csv -> dict[(Entreprise, Annee)] = {"Action":..., "Raison":...}"""
    if not path.exists():
        print(f"ℹ️  Pas de fichier d'overrides trouvé à {path} (optionnel, on continue sans).")
        return {}

    overrides = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["Entreprise"].strip(), row["Annee"].strip())
            action = row["Action"].strip().lower()
            if action not in ("remplacer", "garder_original"):
                print(f"⚠️  Action invalide ignorée pour {key} : '{action}' "
                      f"(doit être 'remplacer' ou 'garder_original')")
                continue
            overrides[key] = {
                "Action": action,
                "Raison": row.get("Raison", "").strip(),
                "Fichier_candidat_override": row.get("Fichier_candidat_override", "").strip(),
                "Pages_candidat_override": row.get("Pages_candidat_override", "").strip(),
            }
    print(f"✅ {len(overrides)} override(s) manuel(s) chargé(s) depuis {path}")
    return overrides


def main():
    parser = argparse.ArgumentParser(description="Génère le fichier de décisions de remplacement.")
    parser.add_argument("--quality", type=Path, default=Path("smart_test_output/QUALITY_CHECK.csv"))
    parser.add_argument("--overrides", type=Path, default=Path("overrides.csv"))
    parser.add_argument("--out", type=Path, default=Path("smart_test_output/REPLACEMENT_DECISIONS.csv"))
    args = parser.parse_args()

    if not args.quality.exists():
        print(f"❌ Fichier introuvable : {args.quality}")
        return

    with open(args.quality, "r", encoding="utf-8-sig") as f:
        quality_rows = list(csv.DictReader(f))

    overrides = load_overrides(args.overrides)

    decisions = []
    n_override_applied = 0

    for row in quality_rows:
        entreprise, annee = row["Entreprise"], row["Annee"]
        verdict = row.get("verdict", "")
        key = (entreprise, annee)

        if key in overrides:
            action = overrides[key]["Action"]
            raison = f"OVERRIDE MANUEL : {overrides[key]['Raison']}"
            n_override_applied += 1
            fichier_candidat = overrides[key]["Fichier_candidat_override"] or row.get("Fichier_candidat", "")
            pages_candidat = overrides[key]["Pages_candidat_override"] or row.get("Pages_candidat", "")
        else:
            action = DEFAULT_ACTION_BY_VERDICT.get(verdict, "garder_original")
            raison = f"Défaut selon verdict automatique '{verdict}'"
            fichier_candidat = row.get("Fichier_candidat", "")
            pages_candidat = row.get("Pages_candidat", "")

        decisions.append({
            "Entreprise": entreprise,
            "Annee": annee,
            "Action": action,
            "Verdict_automatique": verdict,
            "Raison": raison,
            "Pages_locales_originales": row.get("Pages_locales_originales", ""),
            "Pages_candidat": pages_candidat,
            "Fichier_candidat": fichier_candidat,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Entreprise", "Annee", "Action", "Verdict_automatique", "Raison",
                  "Pages_locales_originales", "Pages_candidat", "Fichier_candidat"]
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(decisions)

    n_remplacer = sum(1 for d in decisions if d["Action"] == "remplacer")
    n_garder = sum(1 for d in decisions if d["Action"] == "garder_original")

    print("\n" + "=" * 90)
    print("RÉSUMÉ DES DÉCISIONS")
    print(f"  À remplacer          : {n_remplacer}")
    print(f"  À garder (original)  : {n_garder}")
    print(f"  Overrides appliqués  : {n_override_applied}")
    print(f"  -> Fichier généré : {args.out.resolve()}")
    print("  Tu peux encore ouvrir ce CSV et changer manuellement la colonne 'Action'")
    print("  avant de lancer apply_replacements.py.")
    print("=" * 90)


if __name__ == "__main__":
    main()