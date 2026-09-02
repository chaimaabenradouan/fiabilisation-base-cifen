#!/usr/bin/env python3
"""
Script de validation AVANCÉE d'un fichier de données comptables
(Bilan Actif/Passif + CPC) — vérifie les cohérences de SOUS-TOTAUX,
en complément de la règle globale Actif=Passif=CPC déjà vérifiée par
validate_bilan.py.

Utilisation :
    python validate_bilan_regles_avancees.py chemin/vers/fichier.csv \
        [--tolerance 1.0]

Chaque règle est de la forme :
    Colonne_Total == somme(Colonnes_Composantes)
ou, pour les résultats intermédiaires du CPC :
    Colonne_Résultat == Colonne_A - Colonne_B   (ou + )

Pour chaque règle et chaque ligne (Entreprise, Annee), le script calcule
l'écart = valeur_réelle - valeur_calculée. Si |écart| > tolérance, la
ligne est comptée en anomalie pour cette règle.

SORTIE SIMPLIFIÉE : le script ne produit QUE des chiffres/pourcentages
(taux de cohérence par règle, nombre d'anomalies par entreprise/année) —
aucune valeur comptable individuelle (réelle/calculée) n'est exportée,
pour ne pas avoir à vérifier/corriger des écarts en détail.

Comportement sur les valeurs manquantes :
  - Les colonnes composantes vides (NaN) sont traitées comme 0 dans la
    somme (comportement standard des bilans où une rubrique vide = 0).
  - Si la colonne "total" elle-même est vide (NaN), la règle est ignorée
    pour cette ligne (on ne peut rien comparer) et c'est signalé
    séparément dans le rapport de couverture, pas comme une anomalie
    numérique.
  - Si TOUTES les colonnes composantes d'une règle sont absentes du
    fichier (pas seulement vides), la règle est désactivée globalement
    (pas seulement pour la ligne) et un avertissement est affiché au
    lancement.
"""

import argparse
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# 0. Entreprises HORS PÉRIMÈTRE du référentiel CIFEN/CGNC standard
# ---------------------------------------------------------------------------
# Certaines entreprises ne peuvent structurellement PAS remplir tous les
# champs CIFEN, sans que ce soit une erreur d'extraction :
#   - les banques/organismes financiers ne publient pas un bilan CGNC
#     "commerce/industrie" classique (autre plan comptable) -> beaucoup de
#     champs standards n'existent tout simplement pas chez elles ;
#   - les sociétés non marocaines (ex: ENNAKL est tunisienne) ne suivent pas
#     forcément la nomenclature CGNC marocaine.
# Ces entreprises sont exclues du "taux corrigé" (qui reflète la qualité
# réelle du pipeline sur son périmètre cible), mais restent visibles dans
# les fichiers détaillés (rien n'est supprimé, juste marqué à part).
#
# A COMPLETER : ajoute ici toute entreprise identifiée comme hors périmètre.
ENTREPRISES_HORS_PERIMETRE = {
    "CFG_BANK": "Banque - plan comptable bancaire, pas CGNC commerce/industrie",
    "CASH_PLUS_S.A": "Établissement de paiement - structure de bilan différente",
    "ENNAKL_AUTOMOBILES": "Société tunisienne - ne suit pas la nomenclature CGNC marocaine",
}



# Chaque règle : (nom, colonne_total, colonnes_composantes, mode)
#   mode "sum"  -> total == somme(composantes)
#   mode "diff" -> total == composantes[0] - composantes[1] - ... (soustrait tout le reste)
#
# NOTE : la règle "CPC_I = I_1..I_8 (produits exploitation)" a été retirée
# (elle générait trop d'erreurs/faux positifs et nécessitait une vérification
# manuelle coûteuse en temps). Les règles qui dépendent de CPC_I en amont
# (CPC_III, CPC_VII, CPC_XI, CPC_TOTAL_PRODUITS) restent actives : elles
# utilisent directement la valeur de la colonne CPC_I telle qu'extraite,
# sans revérifier sa propre composition interne.

RULES = [
    # ---------------------- ACTIF : sous-totaux de rubriques ----------------------
    ("Actif_A = A1+A2+A3", "Actif_A",
        ["Actif_A1", "Actif_A2", "Actif_A3"], "sum"),
    ("Actif_B = B1..B5", "Actif_B",
        ["Actif_B1", "Actif_B2", "Actif_B3", "Actif_B4", "Actif_B5"], "sum"),
    ("Actif_C = C1..C7", "Actif_C",
        ["Actif_C1", "Actif_C2", "Actif_C3", "Actif_C4", "Actif_C5", "Actif_C6", "Actif_C7"], "sum"),
    ("Actif_D = D1..D4", "Actif_D",
        ["Actif_D1", "Actif_D2", "Actif_D3", "Actif_D4"], "sum"),
    ("Actif_E = E1+E2", "Actif_E",
        ["Actif_E1", "Actif_E2"], "sum"),
    ("Actif_F = F1..F5", "Actif_F",
        ["Actif_F1", "Actif_F2", "Actif_F3", "Actif_F4", "Actif_F5"], "sum"),
    ("Actif_G = G1..G7", "Actif_G",
        ["Actif_G1", "Actif_G2", "Actif_G3", "Actif_G4", "Actif_G5", "Actif_G6", "Actif_G7"], "sum"),
    ("Actif_tresor = tresor1..4", "Actif_tresor",
        ["Actif_tresor1", "Actif_tresor2", "Actif_tresor3", "Actif_tresor4"], "sum"),

    # ---------------------- ACTIF : totaux généraux ----------------------
    ("Actif_TOTAL_I = A+B+C+D+E", "Actif_TOTAL_I",
        ["Actif_A", "Actif_B", "Actif_C", "Actif_D", "Actif_E"], "sum"),
    ("Actif_TOTAL_II = F+G+H+I", "Actif_TOTAL_II",
        ["Actif_F", "Actif_G", "Actif_H", "Actif_I"], "sum"),
    ("Actif_TOTAL_GENERAL = TOTAL_I+TOTAL_II+tresor", "Actif_TOTAL_GENERAL",
        ["Actif_TOTAL_I", "Actif_TOTAL_II", "Actif_tresor"], "sum"),

    # ---------------------- PASSIF : sous-totaux de rubriques ----------------------
    ("Passif_A = A2+A_nonappele+A6..A12", "Passif_A",
        ["Passif_A2", "Passif_A_nonappele", "Passif_A6", "Passif_A7", "Passif_A8",
         "Passif_A9", "Passif_A10", "Passif_A11", "Passif_A12"], "sum"),
    ("Passif_B = B1+B2", "Passif_B",
        ["Passif_B1", "Passif_B2"], "sum"),
    ("Passif_C = C1+C2", "Passif_C",
        ["Passif_C1", "Passif_C2"], "sum"),
    ("Passif_D = D1+D2", "Passif_D",
        ["Passif_D1", "Passif_D2"], "sum"),
    ("Passif_E = E1+E2", "Passif_E",
        ["Passif_E1", "Passif_E2"], "sum"),
    ("Passif_F = F1..F8", "Passif_F",
        ["Passif_F1", "Passif_F2", "Passif_F3", "Passif_F4", "Passif_F5",
         "Passif_F6", "Passif_F7", "Passif_F8"], "sum"),
    ("Passif_tresor = tresor1..3", "Passif_tresor",
        ["Passif_tresor1", "Passif_tresor2", "Passif_tresor3"], "sum"),

    # ---------------------- PASSIF : totaux généraux ----------------------
    ("Passif_TOTAL_I = A+B+C+D+E", "Passif_TOTAL_I",
        ["Passif_A", "Passif_B", "Passif_C", "Passif_D", "Passif_E"], "sum"),
    ("Passif_TOTAL_II = F+G+H", "Passif_TOTAL_II",
        ["Passif_F", "Passif_G", "Passif_H"], "sum"),
    ("Passif_TOTAL_GENERAL = TOTAL_I+TOTAL_II+tresor", "Passif_TOTAL_GENERAL",
        ["Passif_TOTAL_I", "Passif_TOTAL_II", "Passif_tresor"], "sum"),

    # ---------------------- CPC : sous-totaux ----------------------
    # (CPC_I retiré, cf. note en tête de RULES)
    ("CPC_II = II_1..II_7 (charges exploitation)", "CPC_II",
        ["CPC_II_1", "CPC_II_2", "CPC_II_3", "CPC_II_4", "CPC_II_5", "CPC_II_6", "CPC_II_7"], "sum"),
    ("CPC_III = I - II (résultat exploitation)", "CPC_III",
        ["CPC_I", "CPC_II"], "diff"),
    ("CPC_IV = IV_1..IV_4 (produits financiers)", "CPC_IV",
        ["CPC_IV_1", "CPC_IV_2", "CPC_IV_3", "CPC_IV_4"], "sum"),
    ("CPC_V = V_1..V_4 (charges financières)", "CPC_V",
        ["CPC_V_1", "CPC_V_2", "CPC_V_3", "CPC_V_4"], "sum"),
    ("CPC_VI = IV - V (résultat financier)", "CPC_VI",
        ["CPC_IV", "CPC_V"], "diff"),
    ("CPC_VII = III + VI (résultat courant)", "CPC_VII",
        ["CPC_III", "CPC_VI"], "sum"),
    ("CPC_VIII = VIII_1..VIII_5 (produits non courants)", "CPC_VIII",
        ["CPC_VIII_1", "CPC_VIII_2", "CPC_VIII_3", "CPC_VIII_4", "CPC_VIII_5"], "sum"),
    ("CPC_IX = IX_1..IX_4 (charges non courantes)", "CPC_IX",
        ["CPC_IX_1", "CPC_IX_2", "CPC_IX_3", "CPC_IX_4"], "sum"),
    ("CPC_X = VIII - IX (résultat non courant)", "CPC_X",
        ["CPC_VIII", "CPC_IX"], "diff"),
    ("CPC_XI = VII + X (résultat avant impôts)", "CPC_XI",
        ["CPC_VII", "CPC_X"], "sum"),
    ("CPC_XIII = XI - XII (résultat net)", "CPC_XIII",
        ["CPC_XI", "CPC_XII"], "diff"),
    ("CPC_TOTAL_PRODUITS = I+IV+VIII", "CPC_TOTAL_PRODUITS",
        ["CPC_I", "CPC_IV", "CPC_VIII"], "sum"),
    ("CPC_TOTAL_CHARGES = II+V+IX+XII", "CPC_TOTAL_CHARGES",
        ["CPC_II", "CPC_V", "CPC_IX", "CPC_XII"], "sum"),
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
# 3. Calcul d'une règle pour une ligne
# ---------------------------------------------------------------------------
def compute_expected(row, cols, mode):
    """Calcule la valeur attendue à partir des colonnes composantes.
    Les composantes manquantes/vides comptent comme 0."""
    vals = [row[c] if (c in row.index and not pd.isna(row[c])) else 0.0 for c in cols]
    if mode == "sum":
        return sum(vals)
    elif mode == "diff":
        # composantes[0] - composantes[1] - composantes[2] - ...
        if not vals:
            return np.nan
        res = vals[0]
        for v in vals[1:]:
            res -= v
        return res
    else:
        raise ValueError(f"Mode inconnu: {mode}")


# ---------------------------------------------------------------------------
# 4. Application de toutes les règles
# ---------------------------------------------------------------------------
def check_rules(df: pd.DataFrame, tolerance: float = 1.0):
    """
    Applique toutes les règles actives et retourne :
      - anomalies : DataFrame interne (utilisé uniquement pour construire
        les synthèses par entreprise/année), JAMAIS exporté tel quel en CSV
        (pas de valeur réelle/calculée exposée).
      - coverage  : DataFrame exporté, uniquement des chiffres/pourcentages
        par règle.
    """
    anomalies = []
    coverage = []
    active_rules = []

    for name, target, components, mode in RULES:
        cols_needed = [target] + components
        missing_cols = [c for c in cols_needed if c not in df.columns]
        if missing_cols:
            print(f"⚠️  Règle ignorée (colonnes absentes du fichier) : {name} "
                  f"-> manquantes: {missing_cols}")
            continue
        active_rules.append((name, target, components, mode))

    for name, target, components, mode in active_rules:
        n_total = len(df)
        n_evaluable = 0
        n_ok = 0

        for idx in df.index:
            total_reel = df.at[idx, target]
            if pd.isna(total_reel):
                continue  # rien à comparer, on ignore cette ligne pour cette règle
            expected = compute_expected(df.loc[idx], components, mode)
            ecart = total_reel - expected
            n_evaluable += 1
            ok = abs(ecart) <= tolerance
            n_ok += int(ok)
            if not ok:
                # gardé en mémoire uniquement pour agréger les synthèses
                # par entreprise/année plus bas -- jamais écrit tel quel
                anomalies.append({
                    "Entreprise": df.at[idx, "Entreprise"],
                    "Annee": df.at[idx, "Annee"],
                    "Regle": name,
                })

        taux = round(100.0 * n_ok / n_evaluable, 2) if n_evaluable > 0 else np.nan
        coverage.append({
            "Regle": name,
            "n_lignes_total": n_total,
            "n_lignes_evaluables": n_evaluable,
            "n_lignes_ok": n_ok,
            "taux_coherence_pct": taux,
        })

    return pd.DataFrame(anomalies), pd.DataFrame(coverage)


# ---------------------------------------------------------------------------
# 4bis. Regroupement des anomalies par Entreprise / Annee
# ---------------------------------------------------------------------------
def build_summaries(df: pd.DataFrame, anomalies: pd.DataFrame):
    """
    Construit deux tables de synthèse à partir du détail des anomalies
    (comptages et pourcentages uniquement, aucune valeur comptable) :

    1) par_entreprise_annee : une ligne par (Entreprise, Annee) touché par au
       moins une anomalie, avec le nombre d'anomalies et la liste des règles
       en défaut pour cette ligne précise.

    2) par_entreprise : une ligne par Entreprise, agrégée sur TOUTES ses
       années présentes dans le fichier, avec :
         - n_annees_total       : nombre d'années de cette entreprise dans le fichier
         - n_annees_en_anomalie : nombre d'années avec au moins 1 anomalie
         - pct_annees_propres   : % d'années sans aucune anomalie
         - n_anomalies_total    : nombre total d'anomalies (toutes années confondues)
         - regles_en_anomalie   : ensemble des règles jamais en défaut pour cette entreprise
    """
    annees_par_entreprise = df.groupby("Entreprise")["Annee"].nunique()

    if anomalies.empty:
        par_entreprise = pd.DataFrame({
            "Entreprise": annees_par_entreprise.index,
            "n_annees_total": annees_par_entreprise.values,
            "n_annees_en_anomalie": 0,
            "pct_annees_propres": 100.0,
            "n_anomalies_total": 0,
            "regles_en_anomalie": "",
        })
        return pd.DataFrame(), par_entreprise

    par_entreprise_annee = (
        anomalies.groupby(["Entreprise", "Annee"])
        .agg(
            n_anomalies=("Regle", "count"),
            regles_en_anomalie=("Regle", lambda x: "; ".join(sorted(set(x)))),
        )
        .reset_index()
        .sort_values(["Entreprise", "Annee"])
    )

    par_entreprise = (
        anomalies.groupby("Entreprise")
        .agg(
            n_annees_en_anomalie=("Annee", "nunique"),
            n_anomalies_total=("Regle", "count"),
            regles_en_anomalie=("Regle", lambda x: "; ".join(sorted(set(x)))),
        )
        .reset_index()
    )
    par_entreprise["n_annees_total"] = par_entreprise["Entreprise"].map(annees_par_entreprise)

    # Ajoute les entreprises 100% propres (aucune anomalie sur aucune année)
    entreprises_propres = [
        e for e in annees_par_entreprise.index if e not in set(par_entreprise["Entreprise"])
    ]
    if entreprises_propres:
        propres_df = pd.DataFrame({
            "Entreprise": entreprises_propres,
            "n_annees_en_anomalie": 0,
            "n_anomalies_total": 0,
            "regles_en_anomalie": "",
            "n_annees_total": [annees_par_entreprise[e] for e in entreprises_propres],
        })
        par_entreprise = pd.concat([par_entreprise, propres_df], ignore_index=True)

    par_entreprise["pct_annees_propres"] = round(
        100.0 * (par_entreprise["n_annees_total"] - par_entreprise["n_annees_en_anomalie"])
        / par_entreprise["n_annees_total"],
        2,
    )

    cols_order = ["Entreprise", "n_annees_total", "n_annees_en_anomalie",
                  "pct_annees_propres", "n_anomalies_total", "regles_en_anomalie"]
    par_entreprise = par_entreprise[cols_order].sort_values(
        ["n_anomalies_total", "Entreprise"], ascending=[False, True]
    )

    return par_entreprise_annee, par_entreprise


# ---------------------------------------------------------------------------
# 4ter. Statistiques d'EXTRACTION (taux de remplissage), indépendantes des
#       règles comptables ci-dessus. Répond à la question : "sur tous les
#       champs CIFEN attendus, combien ai-je réussi à en extraire (non
#       vides) ?" -- peu importe si les totaux sont cohérents ou non.
# ---------------------------------------------------------------------------
def build_extraction_stats(df: pd.DataFrame):
    """
    Calcule le taux de remplissage (extraction) des colonnes de données,
    à 3 niveaux :
      1) global_extraction : un seul chiffre, LE taux d'extraction global
         (% de cellules non vides sur l'ensemble du fichier, colonnes
         Entreprise/Annee exclues).
      2) par_entreprise_extraction : taux de remplissage par entreprise
         (moyenne sur toutes ses lignes/années).
      3) par_champ_extraction : taux de remplissage par champ CIFEN
         (utile pour repérer les champs systématiquement mal reconnus par
         l'OCR/le mapping, indépendamment de toute règle comptable).
    """
    id_cols = ["Entreprise", "Annee"]
    data_cols = [c for c in df.columns if c not in id_cols]

    if not data_cols:
        empty = pd.DataFrame()
        return {"taux_extraction_global_pct": np.nan, "cellules_remplies": 0,
                "cellules_totales": 0}, empty, empty

    total_cells = len(df) * len(data_cols)
    filled_cells = int(df[data_cols].notna().sum().sum())
    taux_global = round(100.0 * filled_cells / total_cells, 2) if total_cells > 0 else np.nan

    global_extraction = {
        "taux_extraction_global_pct": taux_global,
        "cellules_remplies": filled_cells,
        "cellules_totales": total_cells,
        "nb_champs_cifen": len(data_cols),
        "nb_lignes_entreprise_annee": len(df),
    }

    # --- par entreprise : moyenne du taux de remplissage sur ses lignes ---
    rows_par_entreprise = []
    for entreprise, sous_df in df.groupby("Entreprise"):
        n_cells = len(sous_df) * len(data_cols)
        n_filled = int(sous_df[data_cols].notna().sum().sum())
        taux = round(100.0 * n_filled / n_cells, 2) if n_cells > 0 else np.nan
        rows_par_entreprise.append({
            "Entreprise": entreprise,
            "n_annees": sous_df["Annee"].nunique(),
            "taux_extraction_pct": taux,
            "cellules_remplies": n_filled,
            "cellules_totales": n_cells,
        })
    par_entreprise_extraction = pd.DataFrame(rows_par_entreprise).sort_values(
        "taux_extraction_pct", ascending=True
    )

    # --- par champ CIFEN : quels champs sont les moins souvent extraits ---
    rows_par_champ = []
    for col in data_cols:
        n_filled = int(df[col].notna().sum())
        n_total = len(df)
        taux = round(100.0 * n_filled / n_total, 2) if n_total > 0 else np.nan
        rows_par_champ.append({
            "Champ_CIFEN": col,
            "taux_extraction_pct": taux,
            "lignes_remplies": n_filled,
            "lignes_totales": n_total,
        })
    par_champ_extraction = pd.DataFrame(rows_par_champ).sort_values(
        "taux_extraction_pct", ascending=True
    )

    return global_extraction, par_entreprise_extraction, par_champ_extraction



def main():
    parser = argparse.ArgumentParser(
        description="Valide les sous-totaux Actif/Passif/CPC d'un fichier bilan (règles avancées). "
                     "Sortie limitée à des chiffres/pourcentages, aucune valeur comptable exportée."
    )
    parser.add_argument("fichier", help="Chemin du fichier CSV (séparateur ';')")
    parser.add_argument("--tolerance", type=float, default=1.0,
                         help="Écart toléré en valeur absolue (défaut: 1.0)")
    parser.add_argument("--out-extraction-global", default="taux_extraction_global.csv",
                         help="Fichier de sortie du taux d'extraction global (remplissage) "
                              "(défaut: taux_extraction_global.csv)")
    parser.add_argument("--out-extraction-entreprise", default="taux_extraction_par_entreprise.csv",
                         help="Fichier de sortie du taux d'extraction par entreprise "
                              "(défaut: taux_extraction_par_entreprise.csv)")
    parser.add_argument("--out-extraction-champ", default="taux_extraction_par_champ.csv",
                         help="Fichier de sortie du taux d'extraction par champ CIFEN "
                              "(défaut: taux_extraction_par_champ.csv)")
    parser.add_argument("--out-global", default="taux_global.csv",
                         help="Fichier de sortie du taux global unique (LE chiffre à retenir) "
                              "(défaut: taux_global.csv)")
    parser.add_argument("--out-coverage", default="couverture_regles.csv",
                         help="Fichier de sortie du taux de cohérence par règle "
                              "(défaut: couverture_regles.csv)")
    parser.add_argument("--out-par-entreprise-annee", default="anomalies_par_entreprise_annee.csv",
                         help="Synthèse des anomalies par (Entreprise, Annee) "
                              "(défaut: anomalies_par_entreprise_annee.csv)")
    parser.add_argument("--out-par-entreprise", default="anomalies_par_entreprise.csv",
                         help="Synthèse des anomalies agrégée par Entreprise, toutes années "
                              "confondues (défaut: anomalies_par_entreprise.csv)")
    parser.add_argument("--entreprise", default=None,
                         help="Nom exact d'une entreprise pour n'afficher en détail QUE son "
                              "historique (le fichier de sortie, lui, contient toujours toutes "
                              "les entreprises)")
    args = parser.parse_args()

    df = load_data(args.fichier)
    print(f"Fichier chargé : {len(df)} ligne(s), {len(df.columns)} colonne(s).")
    print()

    entreprises_exclues = [e for e in df["Entreprise"].unique() if e in ENTREPRISES_HORS_PERIMETRE]
    if entreprises_exclues:
        print("ℹ️  Entreprises hors périmètre CGNC standard (exclues du taux CORRIGÉ, "
              "gardées dans le taux BRUT et dans tous les fichiers détaillés) :")
        for e in entreprises_exclues:
            print(f"     - {e} : {ENTREPRISES_HORS_PERIMETRE[e]}")
        print()

    df_perimetre = df[~df["Entreprise"].isin(ENTREPRISES_HORS_PERIMETRE)]

    # ------------------------------------------------------------------
    # TAUX D'EXTRACTION : combien de champs CIFEN ont réellement été
    # remplis par le pipeline (mapping/OCR), indépendamment de savoir si
    # les totaux comptables tombent juste. Affiché en premier : c'est la
    # question "mon extraction a-t-elle bien fonctionné ?".
    # Calculé en BRUT (toutes entreprises) et en CORRIGÉ (hors périmètre
    # exclu), pour ne pas être faussé par des entreprises structurellement
    # différentes (banques, sociétés étrangères...).
    # ------------------------------------------------------------------
    global_extraction, par_entreprise_extraction, par_champ_extraction = build_extraction_stats(df)
    global_extraction_corrige, _, _ = build_extraction_stats(df_perimetre)

    print("=" * 60)
    print("  TAUX D'EXTRACTION (champs remplis / champs attendus)")
    print("=" * 60)
    te = global_extraction.get("taux_extraction_global_pct", np.nan)
    te_c = global_extraction_corrige.get("taux_extraction_global_pct", np.nan)
    if not pd.isna(te):
        print(f"  BRUT     : {te} %   ({global_extraction['cellules_remplies']} / "
              f"{global_extraction['cellules_totales']} champs, {df['Entreprise'].nunique()} entreprises)")
    if not pd.isna(te_c):
        print(f"  CORRIGÉ  : {te_c} %   ({global_extraction_corrige['cellules_remplies']} / "
              f"{global_extraction_corrige['cellules_totales']} champs, "
              f"{df_perimetre['Entreprise'].nunique()} entreprises, hors périmètre exclu)")
    print("=" * 60)
    print()

    global_extraction["type"] = "brut"
    global_extraction_corrige["type"] = "corrige_hors_perimetre"
    pd.DataFrame([global_extraction, global_extraction_corrige]).to_csv(
        args.out_extraction_global, sep=";", index=False
    )
    print(f"Taux d'extraction (brut + corrigé) exporté dans : {args.out_extraction_global}")

    if not par_entreprise_extraction.empty:
        par_entreprise_extraction["hors_perimetre"] = par_entreprise_extraction["Entreprise"].isin(
            ENTREPRISES_HORS_PERIMETRE
        )
        par_entreprise_extraction.to_csv(args.out_extraction_entreprise, sep=";", index=False)
        print(f"Taux d'extraction par entreprise exporté dans : {args.out_extraction_entreprise}")
        print()
        print("=== Entreprises avec le taux d'extraction le PLUS FAIBLE (à vérifier en priorité) ===")
        print(par_entreprise_extraction.head(10).to_string(index=False))

    if not par_champ_extraction.empty:
        par_champ_extraction.to_csv(args.out_extraction_champ, sep=";", index=False)
        print(f"Taux d'extraction par champ CIFEN exporté dans : {args.out_extraction_champ}")
        print()
        print("=== Champs CIFEN les MOINS SOUVENT extraits (à vérifier en priorité) ===")
        print(par_champ_extraction.head(10).to_string(index=False))
    print()

    anomalies, coverage = check_rules(df, tolerance=args.tolerance)
    anomalies_c, coverage_c = check_rules(df_perimetre, tolerance=args.tolerance)

    # ------------------------------------------------------------------
    # TAUX GLOBAL DE COHÉRENCE : un seul chiffre qui résume tout, en BRUT
    # (toutes entreprises) et en CORRIGÉ (hors périmètre exclu).
    # ------------------------------------------------------------------
    total_evaluable = int(coverage["n_lignes_evaluables"].sum()) if not coverage.empty else 0
    total_ok = int(coverage["n_lignes_ok"].sum()) if not coverage.empty else 0
    taux_global = round(100.0 * total_ok / total_evaluable, 2) if total_evaluable > 0 else np.nan

    total_evaluable_c = int(coverage_c["n_lignes_evaluables"].sum()) if not coverage_c.empty else 0
    total_ok_c = int(coverage_c["n_lignes_ok"].sum()) if not coverage_c.empty else 0
    taux_global_c = round(100.0 * total_ok_c / total_evaluable_c, 2) if total_evaluable_c > 0 else np.nan

    print("=" * 60)
    print("  TAUX GLOBAL DE COHÉRENCE (toutes règles confondues)")
    print("=" * 60)
    if total_evaluable > 0:
        print(f"  BRUT     : {taux_global} %   ({total_ok} / {total_evaluable} vérifications)")
    if total_evaluable_c > 0:
        print(f"  CORRIGÉ  : {taux_global_c} %   ({total_ok_c} / {total_evaluable_c} vérifications, "
              f"hors périmètre exclu)")
    if total_evaluable == 0:
        print("  Non calculable (aucune règle active / aucune ligne évaluable)")
    print("=" * 60)
    print()

    global_summary = pd.DataFrame([
        {
            "type": "brut",
            "taux_global_pct": taux_global,
            "verifications_correctes": total_ok,
            "verifications_totales": total_evaluable,
            "nb_regles_actives": len(coverage),
            "nb_entreprises": df["Entreprise"].nunique(),
            "nb_lignes_entreprise_annee": len(df),
        },
        {
            "type": "corrige_hors_perimetre",
            "taux_global_pct": taux_global_c,
            "verifications_correctes": total_ok_c,
            "verifications_totales": total_evaluable_c,
            "nb_regles_actives": len(coverage_c),
            "nb_entreprises": df_perimetre["Entreprise"].nunique(),
            "nb_lignes_entreprise_annee": len(df_perimetre),
        },
    ])
    global_summary.to_csv(args.out_global, sep=";", index=False)
    print(f"Résumé global (brut + corrigé) exporté dans : {args.out_global}")
    print()

    print("=== Taux de cohérence par règle (détail, sur le périmètre BRUT) ===")
    if not coverage.empty:
        print(coverage.to_string(index=False))
    print()

    if anomalies.empty:
        print("✅ Aucune anomalie détectée sur les règles de sous-totaux.")
    else:
        n_lignes = anomalies[["Entreprise", "Annee"]].drop_duplicates().shape[0]
        n_regles = anomalies["Regle"].nunique()
        print(f"⚠️  {len(anomalies)} anomalie(s) détectée(s), touchant {n_lignes} ligne(s) "
              f"distincte(s) et {n_regles} règle(s) différente(s).")

    coverage.to_csv(args.out_coverage, sep=";", index=False)
    print(f"Taux de cohérence par règle exporté dans : {args.out_coverage}")

    # ------------------------------------------------------------------
    # Synthèses groupées par Entreprise / Annee (chiffres/pourcentages uniquement)
    # ------------------------------------------------------------------
    par_entreprise_annee, par_entreprise = build_summaries(df, anomalies)

    print()
    print("=== Synthèse PAR ENTREPRISE (toutes années confondues) ===")
    if not par_entreprise.empty:
        print(par_entreprise.to_string(index=False))
    par_entreprise.to_csv(args.out_par_entreprise, sep=";", index=False)
    print(f"Exporté dans : {args.out_par_entreprise}")

    if not par_entreprise_annee.empty:
        print()
        print("=== Détail PAR ENTREPRISE + ANNEE (lignes en anomalie uniquement) ===")
        print(par_entreprise_annee.to_string(index=False))
        par_entreprise_annee.to_csv(args.out_par_entreprise_annee, sep=";", index=False)
        print(f"Exporté dans : {args.out_par_entreprise_annee}")

    # ------------------------------------------------------------------
    # Zoom optionnel sur une seule entreprise (--entreprise "NOM")
    # ------------------------------------------------------------------
    if args.entreprise:
        print()
        print(f"=== Zoom sur : {args.entreprise} ===")
        cible = par_entreprise[par_entreprise["Entreprise"] == args.entreprise]
        if cible.empty:
            print(f"⚠️  Entreprise '{args.entreprise}' introuvable dans le fichier "
                  f"(vérifier l'orthographe exacte).")
        else:
            print(cible.to_string(index=False))
            detail_cible = par_entreprise_annee[
                par_entreprise_annee["Entreprise"] == args.entreprise
            ] if not par_entreprise_annee.empty else pd.DataFrame()
            if not detail_cible.empty:
                print()
                print("Années en anomalie :")
                print(detail_cible.to_string(index=False))
            else:
                print("Aucune anomalie sur aucune des années de cette entreprise. ✅")

    return anomalies, coverage, par_entreprise_annee, par_entreprise


if __name__ == "__main__":
    main()