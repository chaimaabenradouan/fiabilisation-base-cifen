#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_replacements.py
=========================================================================
SEUL script qui touche réellement à Rapports/. Conçu pour être sûr :

    1. --dry-run est ACTIF PAR DÉFAUT. Rien n'est modifié tant que tu ne
       passes pas explicitement --execute.
    2. Chaque original remplacé est D'ABORD déplacé (jamais supprimé)
       vers Rapports_backup_originaux/<ENTREPRISE>/<ANNEE>.pdf, qui
       reproduit exactement la structure de Rapports/. Rien n'est perdu.
    3. Idempotent : si un original a déjà été sauvegardé lors d'un run
       précédent, il n'est pas re-déplacé (évite d'écraser une sauvegarde
       par une version déjà remplacée en cas de relance).
    4. Un rapport détaillé de chaque action est affiché ET sauvegardé.

Lit REPLACEMENT_DECISIONS.csv (généré par generate_replacement_decisions.py,
et que tu as pu éditer à la main). Ne traite QUE les lignes Action="remplacer".

Usage :
    # 1) TOUJOURS commencer par une simulation (rien n'est modifié) :
    python apply_replacements.py

    # 2) Une fois que la simulation te semble correcte, exécuter pour de vrai :
    python apply_replacements.py --execute

Sorties :
    Rapports/<ENTREPRISE>/<ANNEE>.pdf              <- remplacé (si --execute)
    Rapports_backup_originaux/<ENTREPRISE>/<ANNEE>.pdf  <- original sauvegardé
    smart_test_output/APPLY_REPORT.csv             <- rapport de chaque action
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

DEFAULT_DECISIONS_CSV = Path("smart_test_output/REPLACEMENT_DECISIONS.csv")
DEFAULT_RAPPORTS_DIR = Path("Rapports")
DEFAULT_BACKUP_DIR = Path("Rapports_backup_originaux")
DEFAULT_REPORT_CSV = Path("smart_test_output/APPLY_REPORT.csv")


def process_row(row: dict, rapports_dir: Path, backup_dir: Path, execute: bool) -> dict:
    entreprise, annee = row["Entreprise"], row["Annee"]
    candidat_path = Path(row["Fichier_candidat"])
    pages_avant = row.get("Pages_locales_originales", "")
    pages_apres = row.get("Pages_candidat", "")

    original_path = rapports_dir / entreprise / f"{annee}.pdf"
    backup_path = backup_dir / entreprise / f"{annee}.pdf"

    result = {
        "Entreprise": entreprise, "Annee": annee,
        "Pages_avant": pages_avant, "Pages_apres": pages_apres,
        "Statut": "", "Detail": "",
    }

    if not candidat_path.exists():
        result["Statut"] = "ERREUR"
        result["Detail"] = f"Candidat introuvable : {candidat_path}"
        return result

    if not original_path.exists():
        result["Statut"] = "ERREUR"
        result["Detail"] = f"Original introuvable dans Rapports/ : {original_path}"
        return result

    already_backed_up = backup_path.exists()

    if not execute:
        action_desc = (
            f"[SIMULATION] déplacerait {original_path} -> {backup_path}"
            + (" (déjà sauvegardé, serait ignoré)" if already_backed_up else "")
            + f" puis copierait {candidat_path} -> {original_path}"
        )
        result["Statut"] = "SIMULE"
        result["Detail"] = action_desc
        return result

    try:
        if not already_backed_up:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(original_path), str(backup_path))
        else:
            # Original déjà sauvegardé lors d'un run précédent : on ne
            # touche pas à la sauvegarde existante, on écrase juste le
            # fichier courant dans Rapports/ (qui est soit l'original
            # non encore remplacé, soit déjà le candidat d'un run précédent).
            original_path.unlink(missing_ok=True)

        original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(candidat_path), str(original_path))

        result["Statut"] = "REMPLACE"
        result["Detail"] = f"Original sauvegardé dans {backup_path} ; candidat copié vers {original_path}"
    except Exception as exc:
        result["Statut"] = "ERREUR"
        result["Detail"] = str(exc)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Applique les remplacements de PDF validés. DRY-RUN par défaut."
    )
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS_CSV)
    parser.add_argument("--rapports-dir", type=Path, default=DEFAULT_RAPPORTS_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_CSV)
    parser.add_argument("--execute", action="store_true",
                         help="Applique réellement les changements. SANS ce flag, "
                              "le script ne fait qu'une simulation (dry-run).")
    args = parser.parse_args()

    if not args.decisions.exists():
        print(f"❌ Fichier introuvable : {args.decisions} "
              f"(lance d'abord generate_replacement_decisions.py)")
        return

    with open(args.decisions, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    to_replace = [r for r in rows if r.get("Action", "").strip().lower() == "remplacer"]

    mode = "EXÉCUTION RÉELLE" if args.execute else "SIMULATION (dry-run, rien ne sera modifié)"
    print(f"=== Mode : {mode} ===")
    print(f"{len(to_replace)} PDF à remplacer sur {len(rows)} lignes au total.\n")

    if not args.execute:
        print("⚠️  Aucune modification ne sera faite. Relance avec --execute pour appliquer réellement.\n")

    results = []
    for row in to_replace:
        res = process_row(row, args.rapports_dir, args.backup_dir, args.execute)
        results.append(res)
        print(f"   [{res['Statut']:<10}] {res['Entreprise']} / {res['Annee']} : "
              f"{res['Pages_avant']} pages -> {res['Pages_apres']} pages | {res['Detail']}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["Entreprise", "Annee", "Pages_avant", "Pages_apres", "Statut", "Detail"])
        writer.writeheader()
        writer.writerows(results)

    n_ok = sum(1 for r in results if r["Statut"] == "REMPLACE")
    n_sim = sum(1 for r in results if r["Statut"] == "SIMULE")
    n_err = sum(1 for r in results if r["Statut"] == "ERREUR")

    def to_int(v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    gain_total = sum(
        to_int(r["Pages_avant"]) - to_int(r["Pages_apres"])
        for r in results if r["Statut"] in ("REMPLACE", "SIMULE")
    )

    print("\n" + "=" * 90)
    if args.execute:
        print(f"TERMINÉ : {n_ok} remplacé(s), {n_err} erreur(s).")
        print(f"Gain total : {gain_total} pages en moins à traiter par MinerU.")
        print(f"Originaux sauvegardés dans : {args.backup_dir.resolve()}")
    else:
        print(f"SIMULATION TERMINÉE : {n_sim} remplacement(s) prévu(s), {n_err} erreur(s) détectée(s).")
        print("Relance avec --execute quand tu es prêt.")
    print(f"Rapport détaillé : {args.report.resolve()}")
    print("=" * 90)


if __name__ == "__main__":
    main()