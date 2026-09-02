#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_financial_data.py
================================================================================
Verifie la coherence financiere/comptable des donnees extraites (table2 -
indicateurs economiques et financiers), pour detecter les erreurs OCR
residuelles SANS avoir besoin de regarder les images. Principe : plusieurs
grandeurs de ce tableau sont liees par des identites comptables qui DOIVENT
etre vraies -- une violation signale presque toujours une valeur mal lue,
pas une vraie anomalie financiere de l'entreprise.

Regles implementees :

R1 - Solde technique = Cotisations et contributions - Pensions et prestations
     (vrai pour les caisses de retraite/secu : CMR, CNSS RG, CNSS AMO).
     Tolerance +/-2 (arrondis d'affichage). Detecte en particulier les
     SIGNES MANQUANTS (valeur correcte en magnitude, signe errone).

R2 - Total actif >= Fonds propres (l'actif finance les capitaux propres +
     les dettes, donc actif >= capitaux propres, toujours).

R3 - Total actif >= Dettes de financement (meme logique).

R4 - Chiffre d'affaires >= Valeur ajoutee (la VA est un sous-agregat du CA,
     ne peut jamais le depasser).

R5 - Charges de personnel / Effectif dans une fourchette plausible
     (30 000 - 900 000 MAD/employe/an). Detecte les effectifs ou charges
     de personnel mal lus (ex: un chiffre tronque ou un zero en trop).

R6 - Coherence annee-sur-annee des grandeurs de "stock" (Effectif, Total
     actif, Fonds propres, Dettes de financement) : un ratio > 3x ou < 1/3x
     d'une annee a l'autre est suspect pour ce type de grandeur (contrairement
     au resultat net ou au CAF qui peuvent legitimement varier fortement).

R7 - Signe attendu : Effectif et Total actif doivent etre strictement positifs.

R8 - Completude : signale les entreprises avec trop peu de champs remplis
     (indice que l'extraction a largement echoue sur cette page, ancre ou
     OCR en cause).

USAGE:
    python3 validate_financial_data.py chemin/vers/table2.csv
    python3 validate_financial_data.py chemin/vers/table2.csv --out rapport.csv

Sortie : rapport lisible dans le terminal + CSV detaille (une ligne par
anomalie detectee, avec _dossier, regle, severite, message, valeurs en jeu).
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

FIELD_RE = re.compile(r"^(?P<prefix>.*?)_?annee_(?P<year>\d+)$")

# grandeurs de "stock" (bilan) : doivent rester relativement stables
# d'une annee sur l'autre, contrairement aux grandeurs de "flux" (resultat,
# CAF...) qui peuvent legitimement varier fortement voire changer de signe.
# NOTE : fonds_propres est volontairement EXCLU -- une recapitalisation ou
# une augmentation de capital peut le faire bondir legitimement (confirme
# empiriquement sur RAM : x3 reel, pas une erreur d'OCR). Contrairement a
# effectif/total_actif/dettes_financement, une variation brutale des
# fonds propres n'est pas structurellement suspecte.
STOCK_INDICATORS = {"effectif", "effectif_du_groupe", "total_actif", "dettes_financement"}

# bases connues utilisees par les regles R1 (identite technique des caisses
# de retraite/secu). Le "prefixe" (ex: regime_general_, assurance_maladie_
# obligatoire_, ou vide pour CMR) est detecte automatiquement.
R1_BASES = {
    "cotisations": "cotisations_contributions",
    "pensions": "pensions_prestations",
    "solde": "solde_technique",
}

TOLERANCE_R1 = 2.0  # arrondi d'affichage (les MDH sont arrondis a l'unite)


def parse_row_fields(row: dict):
    """Regroupe les colonnes '<prefixe>_<base>_annee_<n>' -> {(prefixe,
    base): {n: valeur}}. Le prefixe peut etre vide (indicateurs "globaux"
    de l'entreprise) ou nommer une sous-section (ex: 'regime_general')."""
    groups = defaultdict(dict)
    for col, raw in row.items():
        if col in ("_dossier", "_warning_ancre"):
            continue
        m = FIELD_RE.match(col)
        if not m:
            continue
        year = int(m.group("year"))
        base_full = m.group("prefix")

        # separe prefixe de sous-section (regime_general_, assurance_
        # maladie_obligatoire_) du nom d'indicateur lui-meme, pour les
        # bases connues utilisees par R1
        prefix, base = "", base_full
        for known_base in ("cotisations_contributions", "pensions_prestations", "solde_technique",
                           "total_actif", "fonds_propres"):
            if base_full == known_base:
                prefix, base = "", known_base
                break
            if base_full.endswith("_" + known_base):
                prefix = base_full[: -(len(known_base) + 1)]
                base = known_base
                break

        try:
            val = float(raw) if raw not in (None, "",) else None
        except ValueError:
            val = None
        if val is not None:
            groups[(prefix, base)][year] = val
    return groups


def check_r1_solde_technique(dossier, groups, issues):
    prefixes = {p for p, b in groups if b in ("cotisations_contributions", "pensions_prestations", "solde_technique")}
    for prefix in prefixes:
        cotis = groups.get((prefix, "cotisations_contributions"), {})
        pensions = groups.get((prefix, "pensions_prestations"), {})
        solde = groups.get((prefix, "solde_technique"), {})
        for year in set(cotis) & set(pensions) & set(solde):
            expected = cotis[year] - pensions[year]
            actual = solde[year]
            diff = actual - expected
            label = f"{prefix + '_' if prefix else ''}solde_technique_annee_{year}"
            if abs(diff) > TOLERANCE_R1:
                if abs(abs(actual) - abs(expected)) <= TOLERANCE_R1 and (actual >= 0) != (expected >= 0):
                    # inversion de signe pure (magnitude quasi identique) :
                    # quasiment toujours une vraie erreur d'extraction
                    # (confirme : cas CMR)
                    issues.append((dossier, "R1", "ERREUR", label,
                                   f"signe probablement incorrect : {actual:g} lu, attendu {expected:g} "
                                   f"(cotisations {cotis[year]:g} - pensions {pensions[year]:g})"))
                else:
                    # ecart de MAGNITUDE (pas juste le signe) : moins fiable
                    # en ERREUR certaine -- confirme sur CNSS AMO que
                    # l'identite peut ne pas tenir exactement (3e composante
                    # "Unite Medicale" mentionnee en note de bas de page,
                    # non capturee separement). Severite abaissee en ALERTE.
                    issues.append((dossier, "R1", "ALERTE", label,
                                   f"{actual:g} lu, ecart de {diff:g} vs {expected:g} attendu "
                                   f"(cotisations {cotis[year]:g} - pensions {pensions[year]:g}) "
                                   f"-- peut etre legitime si une 3e composante existe (ex: Unite Medicale pour la CNSS)"))


def check_r2_r3_bilan(dossier, groups, issues):
    prefixes = {p for p, b in groups}
    for prefix in prefixes:
        actif = groups.get((prefix, "total_actif"), {})
        propres = groups.get((prefix, "fonds_propres"), {})
        dettes = groups.get((prefix, "dettes_financement"), {})
        for year in set(actif) & set(propres):
            if actif[year] < propres[year]:
                issues.append((dossier, "R2", "ERREUR", f"total_actif/fonds_propres_annee_{year}",
                               f"total actif ({actif[year]:g}) < fonds propres ({propres[year]:g}) -- impossible"))
        for year in set(actif) & set(dettes):
            if actif[year] < dettes[year]:
                issues.append((dossier, "R3", "ERREUR", f"total_actif/dettes_financement_annee_{year}",
                               f"total actif ({actif[year]:g}) < dettes de financement ({dettes[year]:g}) -- suspect"))


def check_r4_ca_va(dossier, groups, issues):
    ca = groups.get(("", "chiffre_affaires"), {})
    va = groups.get(("", "valeur_ajoutee"), {})
    for year in set(ca) & set(va):
        if va[year] > ca[year]:
            issues.append((dossier, "R4", "ERREUR", f"chiffre_affaires/valeur_ajoutee_annee_{year}",
                           f"valeur ajoutee ({va[year]:g}) > chiffre d'affaires ({ca[year]:g}) -- impossible"))


def check_r5_cout_employe(dossier, groups, issues):
    charges = groups.get(("", "charges_de_personnel"), {})
    effectif = groups.get(("", "effectif"), {}) or groups.get(("", "effectif_du_groupe"), {})
    for year in set(charges) & set(effectif):
        if effectif[year] <= 0:
            continue
        cout = charges[year] * 1_000_000 / effectif[year]  # MDH -> MAD, / tete
        if not (30_000 <= cout <= 900_000):
            issues.append((dossier, "R5", "ALERTE", f"charges_de_personnel/effectif_annee_{year}",
                           f"cout moyen/employe = {cout:,.0f} MAD/an (hors fourchette 30k-900k) "
                           f"-- charges={charges[year]:g} MDH, effectif={effectif[year]:g}"))


def check_r6_stabilite_yoy(dossier, groups, issues):
    for (prefix, base), by_year in groups.items():
        if base not in STOCK_INDICATORS:
            continue
        years = sorted(by_year)
        for y1, y2 in zip(years, years[1:]):
            v1, v2 = by_year[y1], by_year[y2]
            if v1 == 0:
                continue
            ratio = v2 / v1
            if ratio > 3 or ratio < 1 / 3:
                label = f"{prefix + '_' if prefix else ''}{base}"
                issues.append((dossier, "R6", "ALERTE", f"{label}_annee_{y1}->{y2}",
                               f"variation x{ratio:.2f} entre annee {y1} ({v1:g}) et annee {y2} ({v2:g}) "
                               f"-- suspect pour une grandeur de bilan"))


def check_r7_signes(dossier, groups, issues):
    for base in ("effectif", "effectif_du_groupe", "total_actif"):
        for year, val in groups.get(("", base), {}).items():
            if val <= 0:
                issues.append((dossier, "R7", "ERREUR", f"{base}_annee_{year}",
                               f"valeur {val:g} <= 0, attendu strictement positif"))


def check_r8_completude(dossier, row, issues, min_fields=3):
    n_filled = sum(1 for k, v in row.items() if k not in ("_dossier", "_warning_ancre") and v not in (None, ""))
    if n_filled < min_fields:
        issues.append((dossier, "R8", "ERREUR", "completude",
                       f"seulement {n_filled} champs remplis sur cette ligne -- extraction probablement en echec"))


def validate_csv(path: Path):
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    issues = []
    for row in rows:
        dossier = row.get("_dossier", "?")
        groups = parse_row_fields(row)
        check_r8_completude(dossier, row, issues)
        check_r1_solde_technique(dossier, groups, issues)
        check_r2_r3_bilan(dossier, groups, issues)
        check_r4_ca_va(dossier, groups, issues)
        check_r5_cout_employe(dossier, groups, issues)
        check_r6_stabilite_yoy(dossier, groups, issues)
        check_r7_signes(dossier, groups, issues)

    return issues


def print_report(issues):
    if not issues:
        print("Aucune anomalie detectee par les regles de validation.")
        return

    by_dossier = defaultdict(list)
    for issue in issues:
        by_dossier[issue[0]].append(issue)

    n_erreurs = sum(1 for i in issues if i[2] == "ERREUR")
    n_alertes = sum(1 for i in issues if i[2] == "ALERTE")
    print(f"{len(issues)} anomalie(s) detectee(s) sur {len(by_dossier)} entreprise(s) "
          f"({n_erreurs} erreur(s), {n_alertes} alerte(s)).\n")

    for dossier in sorted(by_dossier):
        print(f"=== {dossier} ===")
        for _, rule, sev, field, msg in by_dossier[dossier]:
            print(f"  [{sev:7s}] {rule}  {field:45s} {msg}")
        print()


def write_report_csv(issues, out_path: Path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["dossier", "regle", "severite", "champ", "message"])
        writer.writerows(issues)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_path", type=Path, help="CSV table2 (indicateurs economiques et financiers)")
    parser.add_argument("--out", type=Path, default=None, help="Chemin du rapport CSV detaille (optionnel)")
    args = parser.parse_args()

    issues = validate_csv(args.csv_path)
    print_report(issues)

    if args.out:
        write_report_csv(issues, args.out)
        print(f"Rapport detaille -> {args.out.resolve()}")
    elif issues:
        default_out = args.csv_path.parent / f"{args.csv_path.stem}_anomalies.csv"
        write_report_csv(issues, default_out)
        print(f"Rapport detaille -> {default_out.resolve()}")


if __name__ == "__main__":
    main()