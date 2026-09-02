#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_table1_table2.py
================================================================================
Fusionne les CSV table2 (tous les champs) et table1 (seulement quelques
champs choisis) sur la clef commune _dossier (nom d'entreprise).

- Table2 (fichier "principal") : TOUS ses champs sont conserves.
- Table1 (fichier "secondaire") : SEULS les champs choisis sont ajoutes :
  activite, date_creation, sigle, capital_social, classification_juridique.

Le join est un LEFT JOIN cote table2 (aucune entreprise de table2 n'est
perdue), complete par un OUTER partiel : si une entreprise existe UNIQUEMENT
dans table1 (absente de table2), elle est quand meme ajoutee au resultat --
pour ne perdre aucune information -- avec les colonnes table2 vides pour
cette ligne.

USAGE:
    python3 merge_table1_table2.py \
        toutes_entreprise_table2_FINAL.csv \
        toutes_entreprise_table1_v1.csv \
        --out toutes_entreprises_fusionnees.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

# champs a recuperer depuis table1 (en plus de la clef _dossier)
TABLE1_FIELDS_TO_KEEP = [
    "activite",
    "date_creation",
    "sigle",
    "capital_social",
    "classification_juridique",
]

KEY = "_dossier"


def merge(table2_path: Path, table1_path: Path, out_path: Path):
    df2 = pd.read_csv(table2_path, dtype=str)
    df1 = pd.read_csv(table1_path, dtype=str)

    if KEY not in df2.columns:
        sys.exit(f"Erreur : la colonne '{KEY}' est absente de {table2_path.name}")
    if KEY not in df1.columns:
        sys.exit(f"Erreur : la colonne '{KEY}' est absente de {table1_path.name}")

    missing_fields = [f for f in TABLE1_FIELDS_TO_KEEP if f not in df1.columns]
    if missing_fields:
        print(f"Attention : champs absents de {table1_path.name}, ignores : {missing_fields}")

    fields_present = [f for f in TABLE1_FIELDS_TO_KEEP if f in df1.columns]
    df1_reduced = df1[[KEY] + fields_present].copy()

    # detecte les doublons de cle dans chaque fichier -- source frequente
    # de confusion silencieuse lors d'un merge (une entreprise en double
    # multiplierait ses lignes dans le resultat)
    for name, df in (("table2", df2), ("table1", df1_reduced)):
        dup = df[df.duplicated(subset=[KEY], keep=False)]
        if not dup.empty:
            print(f"Attention : {len(dup)} ligne(s) avec un '{KEY}' duplique dans {name} :")
            print(", ".join(sorted(dup[KEY].unique())))

    # OUTER merge : garde toutes les entreprises des deux fichiers (aucune
    # perte d'information), meme si l'une des deux ne connait pas cette
    # entreprise -- ses colonnes resteront vides pour cette ligne.
    merged = df2.merge(df1_reduced, on=KEY, how="outer", indicator=True)

    only_table2 = merged[merged["_merge"] == "left_only"][KEY].tolist()
    only_table1 = merged[merged["_merge"] == "right_only"][KEY].tolist()
    if only_table2:
        print(f"\n{len(only_table2)} entreprise(s) presente(s) SEULEMENT dans table2 (pas dans table1) :")
        print(", ".join(only_table2))
    if only_table1:
        print(f"\n{len(only_table1)} entreprise(s) presente(s) SEULEMENT dans table1 (pas dans table2) :")
        print(", ".join(only_table1))

    merged = merged.drop(columns=["_merge"])

    # ordre des colonnes : _dossier en premier, puis les champs table1
    # ajoutes (plus visibles juste apres la clef), puis le reste de table2
    other_cols = [c for c in merged.columns if c not in ([KEY] + fields_present)]
    merged = merged[[KEY] + fields_present + other_cols]

    merged.to_csv(out_path, index=False)
    print(f"\n{len(merged)} ligne(s) au total -> {out_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("table2_csv", type=Path, help="CSV principal (tous les champs conserves)")
    parser.add_argument("table1_csv", type=Path, help="CSV secondaire (seulement quelques champs recuperes)")
    parser.add_argument("--out", type=Path, default=Path("toutes_entreprises_fusionnees.csv"))
    args = parser.parse_args()

    merge(args.table2_csv, args.table1_csv, args.out)


if __name__ == "__main__":
    main()