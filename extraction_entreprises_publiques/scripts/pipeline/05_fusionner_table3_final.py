#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fusionne fusion_finale.csv (indicateurs économiques) avec le CSV
Immo. corporelles.

- Jointure sur la colonne _dossier
- Ajoute uniquement les colonnes d'actifs corporels du 2e fichier
- Exclut _diag_avg_score et _warning_ancre (de n'importe quel fichier)
- Produit datafinale.csv
"""

import pandas as pd
from pathlib import Path

# ------------------------------------------------------------------
# Chemins (adapte si besoin)
# ------------------------------------------------------------------
FILE1 = Path("../output/fusion_finale.csv")          # indicateurs principaux
FILE2 = Path("../output/toutes_entreprises_table3_v1.csv")  # ou le nom exact du 2e CSV
OUTPUT = Path("../output/datafinale.csv")

# Colonnes à exclure systématiquement
EXCLUDE = {"_diag_avg_score", "_warning_ancre"}

def main():
    # Lecture
    df1 = pd.read_csv(FILE1, dtype=str)
    df2 = pd.read_csv(FILE2, dtype=str)

    # Nettoyage des noms de colonnes (espaces éventuels)
    df1.columns = df1.columns.str.strip()
    df2.columns = df2.columns.str.strip()

    # Colonnes du 2e fichier à garder (tout sauf les diagnostics + la clé)
    cols_to_add = [c for c in df2.columns
                   if c not in EXCLUDE and c != "_dossier"]

    # On ne garde que la clé + les colonnes utiles du 2e fichier
    df2_clean = df2[["_dossier"] + cols_to_add].copy()

    # Fusion (left join pour conserver toutes les entreprises de fusion_finale)
    merged = df1.merge(df2_clean, on="_dossier", how="left", suffixes=("", "_immo"))

    # Suppression éventuelle des colonnes diagnostics qui auraient pu rester
    for col in EXCLUDE:
        if col in merged.columns:
            merged = merged.drop(columns=[col])

    # Écriture
    merged.to_csv(OUTPUT, index=False, encoding="utf-8")
    print(f"✅ Fichier créé : {OUTPUT.resolve()}")
    print(f"   {len(merged)} lignes × {len(merged.columns)} colonnes")
    print(f"   Colonnes Immo ajoutées : {cols_to_add}")

if __name__ == "__main__":
    main()