#!/usr/bin/env python3
"""
Script de validation d'un fichier de données comptables (Bilan Actif/Passif + CPC).

Utilisation :
    python validate_bilan.py chemin/vers/fichier.csv [--tolerance 1.0] [--out anomalies.csv]

Une seule règle de cohérence croisée est vérifiée, reliant les trois documents :

    Actif_TOTAL_GENERAL == Passif_TOTAL_GENERAL   (équilibre du bilan)
    CPC_XIII (résultat net CPC) == Passif_A12 (résultat net inscrit au Passif)

Pour chaque ligne (Entreprise, Annee) :
    1) le Total Général de l'Actif doit être égal au Total Général du Passif ;
    2) le résultat net du CPC (CPC_XIII) doit être égal au résultat net inscrit
       au Passif (Passif_A12).

NOTE IMPORTANTE : dans le mapping cifen_extractor.py, "CPC_XIV" correspond au
champ [EXT] "Résultat par action" et NON au résultat net -- ne pas l'utiliser
ici. Le résultat net (ligne XIII du CPC marocain, "Résultat net (XI-XII)" /
"Résultat net total produits moins total charges") est bien mappé sur CPC_XIII.

Si les deux égalités sont vérifiées, la ligne est jugée cohérente (Actif = Passif
= CPC). Sinon, elle est signalée en anomalie avec le détail de l'écart.
"""

import argparse
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# 1. Colonnes nécessaires à la règle unique
# ---------------------------------------------------------------------------
REQUIRED_COLS = [
    "Actif_TOTAL_GENERAL",
    "Passif_TOTAL_GENERAL",
    "Passif_A12",     # Résultat net inscrit au Passif
    "CPC_XIII",        # Résultat net du CPC (ATTENTION : CPC_XIV = "Résultat par
                        # action" dans le mapping cifen_extractor.py, PAS le
                        # résultat net -- ne pas confondre)
]


# ---------------------------------------------------------------------------
# 2. Chargement / nettoyage
# ---------------------------------------------------------------------------
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", decimal=".", encoding="utf-8")
    id_cols = ["Entreprise", "Annee"]
    num_cols = [c for c in df.columns if c not in id_cols]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# 3. Règle unique de cohérence croisée Actif / Passif / CPC
# ---------------------------------------------------------------------------
def check_rule(df: pd.DataFrame, tolerance: float = 1.0):
    """
    Retourne (anomalies_df, taux_dict).

    taux_dict contient le taux de cohérence (en %) :
        - "bilan"     : proportion de lignes où Actif_TOTAL_GENERAL == Passif_TOTAL_GENERAL
        - "resultat"  : proportion de lignes où CPC_XIII == Passif_A12
        - "global"    : proportion de lignes où les DEUX égalités sont vérifiées
    """
    anomalies = []
    n_total = len(df)
    n_bilan_ok = 0
    n_resultat_ok = 0
    n_global_ok = 0

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Colonne(s) manquante(s) pour appliquer la règle de cohérence : {missing}"
        )

    for idx in df.index:
        actif_total = df.at[idx, "Actif_TOTAL_GENERAL"]
        passif_total = df.at[idx, "Passif_TOTAL_GENERAL"]
        resultat_passif = df.at[idx, "Passif_A12"]
        resultat_cpc = df.at[idx, "CPC_XIII"]

        ecart_bilan = np.nan if pd.isna(actif_total) or pd.isna(passif_total) \
            else actif_total - passif_total
        ecart_resultat = np.nan if pd.isna(resultat_cpc) or pd.isna(resultat_passif) \
            else resultat_cpc - resultat_passif

        bilan_ok = not pd.isna(ecart_bilan) and abs(ecart_bilan) <= tolerance
        resultat_ok = not pd.isna(ecart_resultat) and abs(ecart_resultat) <= tolerance

        n_bilan_ok += int(bilan_ok)
        n_resultat_ok += int(resultat_ok)
        n_global_ok += int(bilan_ok and resultat_ok)

        if not (bilan_ok and resultat_ok):
            anomalies.append({
                "Entreprise": df.at[idx, "Entreprise"],
                "Annee": df.at[idx, "Annee"],
                "Regle": "Cohérence Actif = Passif = CPC",
                "Actif_TOTAL_GENERAL": actif_total,
                "Passif_TOTAL_GENERAL": passif_total,
                "Ecart_Actif_Passif": ecart_bilan,
                "CPC_XIII": resultat_cpc,
                "Passif_A12": resultat_passif,
                "Ecart_Resultat_CPC_Passif": ecart_resultat,
            })

    def taux(n_ok):
        return round(100.0 * n_ok / n_total, 2) if n_total > 0 else 0.0

    taux_dict = {
        "taux_coherence_bilan_pct": taux(n_bilan_ok),
        "taux_coherence_resultat_pct": taux(n_resultat_ok),
        "taux_coherence_global_pct": taux(n_global_ok),
        "n_lignes_total": n_total,
        "n_lignes_bilan_ok": n_bilan_ok,
        "n_lignes_resultat_ok": n_resultat_ok,
        "n_lignes_global_ok": n_global_ok,
    }

    return pd.DataFrame(anomalies), taux_dict


# ---------------------------------------------------------------------------
# 4. Programme principal
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Valide un fichier bilan/CPC (une seule règle: cohérence Actif = Passif = CPC)."
    )
    parser.add_argument("fichier", help="Chemin du fichier CSV (séparateur ';')")
    parser.add_argument("--tolerance", type=float, default=1.0,
                         help="Écart toléré en valeur absolue (défaut: 1.0)")
    parser.add_argument("--out", default="anomalies.csv",
                         help="Fichier de sortie des anomalies (défaut: anomalies.csv)")
    args = parser.parse_args()

    df = load_data(args.fichier)
    print(f"Fichier chargé : {len(df)} ligne(s), {len(df.columns)} colonne(s).")

    anomalies, taux = check_rule(df, tolerance=args.tolerance)

    print()
    print("=== Taux de cohérence ===")
    print(f"Bilan (Actif = Passif)       : {taux['taux_coherence_bilan_pct']}%  "
          f"({taux['n_lignes_bilan_ok']}/{taux['n_lignes_total']} lignes)")
    print(f"Résultat (CPC = Passif)      : {taux['taux_coherence_resultat_pct']}%  "
          f"({taux['n_lignes_resultat_ok']}/{taux['n_lignes_total']} lignes)")
    print(f"Cohérence globale (les deux) : {taux['taux_coherence_global_pct']}%  "
          f"({taux['n_lignes_global_ok']}/{taux['n_lignes_total']} lignes)")
    print()

    if anomalies.empty:
        print("✅ Aucune anomalie détectée : Actif = Passif = CPC pour toutes les lignes.")
    else:
        n_lignes = anomalies[["Entreprise", "Annee"]].drop_duplicates().shape[0]
        print(f"⚠️  {len(anomalies)} ligne(s) en anomalie sur {n_lignes} ligne(s) distincte(s).")
        print()
        print(anomalies.to_string(index=False))
        print()
        anomalies.to_csv(args.out, sep=";", index=False)
        print(f"Détail exporté dans : {args.out}")

    return anomalies, taux


if __name__ == "__main__":
    main()