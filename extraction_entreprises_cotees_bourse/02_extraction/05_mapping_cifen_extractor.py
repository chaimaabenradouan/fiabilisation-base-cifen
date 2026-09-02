#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cifen_extractor.py
===================

Pipeline d'extraction et de mapping CIFEN pour bilans marocains (ACTIF / PASSIF / CPC)
issus d'une extraction docling (CSV séparés par ";").

STRUCTURE ATTENDUE SUR DISQUE
------------------------------
output/{entreprise}/{annee}/docling_result/tables_csv/bilan_actif.csv
output/{entreprise}/{annee}/docling_result/tables_csv/bilan_passif.csv
output/{entreprise}/{annee}/docling_result/tables_csv/cpc.csv

(fallback automatique : si le sous-dossier tables_csv n'existe pas, le script
cherche récursivement le fichier sous docling_result/)

SORTIES (à la racine de l'entreprise : output/{entreprise}/)
--------------------------------------------------------------
data_complet.csv               -> Bilan;Champ_Original;Annee;Valeur (toutes années, y compris bonus)
data_cifen.csv                 -> TABLEAU LARGE : Entreprise;Annee;<un champ CIFEN par colonne>
data_verification.csv          -> Années DERIVEES (via N-1) pour lesquelles un vrai rapport existe
                                   aussi sur le disque : valeur dérivée vs valeur réelle du rapport.
_non_mappes.csv                -> lignes qui n'ont pas pu être associées à un code CIFEN
_matches_incertains.csv        -> lignes mappées mais avec un score de confiance faible : à auditer
_erreurs.log                   -> erreurs de lecture

SORTIE GLOBALE (à la racine du PROJET, pas de l'entreprise)
--------------------------------------------------------------
data_totale.csv (par défaut, chemin modifiable via --totale-path)
    -> même format "tableau large" que data_cifen.csv, cumulatif sur TOUTES les entreprises.
       Relancer une entreprise déjà présente ne remplace QUE ses lignes (clé Entreprise+Annee).

LOGIQUE "annee courante -> annee precedente" (pour ne pas retraiter deux fois)
-------------------------------------------------------------------------------
  - On trie les années demandées en ordre décroissant.
  - Chaque "ancre" (rapport réellement ouvert) donne 2 années : elle-même (colonne "Net")
    et son N-1 (colonne "Net N-1"), même si N-1 n'était pas demandé (= année "bonus").
  - Pour CHAQUE année obtenue par dérivation (bonus ou demandée), si un vrai rapport
    existe aussi sur le disque pour cette année précise, on l'ouvre EN PLUS, uniquement
    pour comparer (jamais pour remplacer la valeur dérivée) -> data_verification.csv.

MATCHING DES LIBELLÉS OCR -> CODES CIFEN (2 PASSES, ROBUSTE AUX DÉCALAGES)
-----------------------------------------------------------------------------
L'ancienne version avançait un simple "pointeur" ligne par ligne avec une fenêtre de
recherche étroite : dès qu'UNE ligne était mal reconnue (fusionnée par l'OCR, libellé
légèrement différent, ligne vide non prévue...), le pointeur restait décalé et TOUTES
les lignes suivantes de la section pouvaient se retrouver alignées sur le mauvais champ
(effet domino / cascade).

Nouvelle approche :
  1) PASSE 1 (haute confiance, indépendante de la position) : chaque ligne brute est
     comparée à TOUTE la liste canonique (pas juste une fenêtre de 5). Les correspondances
     quasi-certaines (texte très proche) sont validées immédiatement, où qu'elles soient
     dans la liste. Cela plante des "ancres" un peu partout et empêche un décalage de se
     propager sur toute la section.
  2) PASSE 2 (positionnelle, avec marge de sécurité) : pour ce qui reste, recherche autour
     de la position attendue (fenêtre élargie si besoin), mais le match n'est accepté QUE
     s'il dépasse le seuil ET qu'il a une marge suffisante par rapport au 2e meilleur
     candidat. Sinon, la ligne reste NON MAPPÉE plutôt que de deviner un mauvais champ
     (mieux vaut un trou visible dans _non_mappes.csv qu'une fausse valeur silencieuse).

En complément, la colonne "Verification" du CSV source (5e colonne, quand présente)
n'est PAS lue ni interprétée : son contenu a été corrigé/validé manuellement en
amont et n'a plus de signification à analyser automatiquement. Une ligne est
traitée exactement de la même façon que cette colonne soit présente, absente,
vide ou remplie.

USAGE
-----
Mode simple (une entreprise) :
    python cifen_extractor.py afma_SA 2016 2017 2025

Mode "journal" (plusieurs entreprises d'un coup) :
    python cifen_extractor.py --journal mon_journal.csv
    (fichier CSV avec 2 colonnes séparées par ";" : entreprise;annees
     ex:  afma_SA;2016,2017,2025
          autre_ste;2020,2021,2022)

Racine des données (par défaut "output", modifiable) :
    python cifen_extractor.py afma_SA 2016 2017 2025 --root output

Chemin du fichier cumulatif global (par défaut "data_totale.csv" à la racine
du projet, modifiable) :
    python cifen_extractor.py afma_SA 2016 2017 2025 --totale-path data_totale.csv
"""

import argparse
import csv
import difflib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict


# ======================================================================
# 1) DICTIONNAIRES CIFEN (ordre officiel CGNC, tel que fourni)
#    Les entrées marquées [EXT] sont des AJOUTS (lignes de TOTAUX) qui ne
#    figuraient pas dans ta liste de champs d'origine mais qui existent
#    systématiquement dans les bilans et servent à la vérification.
# ======================================================================

# --- ACTIF ------------------------------------------------------------
ACTIF_FIELDS: List[Tuple[str, str]] = [
    ("Actif_A",        "Immobilisations en non valeur"),
    ("Actif_A1",       "Frais préliminaires"),
    ("Actif_A2",       "Charges à répartir sur plusieurs exercices"),
    ("Actif_A3",       "Primes de remboursement des obligations"),
    ("Actif_B",        "Immobilisations incorporelles"),
    ("Actif_B1",       "Immobilisation en recherche et développement"),
    ("Actif_B2",       "Brevets, marques, droits et valeurs similaires"),
    ("Actif_B3",       "Fonds commercial"),
    ("Actif_B4",       "Autres immobilisations incorporelles"),
    ("Actif_B5",       "Immobilisations incorporelles en cours"),  # [EXT: champ hors CIFEN standard mais recurrent]
    ("Actif_C",        "Immobilisations corporelles"),
    ("Actif_C1",       "Terrains"),
    ("Actif_C2",       "Constructions"),
    ("Actif_C2",       "Constructions et agencements de construction"),  # [EXT alias variante frequente]
    ("Actif_C3",       "Installations techniques, matériel et outillage"),
    ("Actif_C4",       "Matériel de transport"),
    ("Actif_C5",       "Mobilier, matériel de bureau et aménagements divers"),
    ("Actif_C6",       "Autres immobilisations corporelles"),
    ("Actif_C7",       "Immobilisations corporelles en cours"),
    ("Actif_D",        "Immobilisations financières"),
    ("Actif_D1",       "Prêts immobilisés"),
    ("Actif_D2",       "Autres créances financières"),
    ("Actif_D3",       "Titres de participation"),
    ("Actif_D4",       "Autres titres immobilisés"),
    ("Actif_E",        "Ecarts de conversion - Actif"),
    ("Actif_E1",       "Diminution des créances immobilisées"),
    ("Actif_E2",       "Augmentation des dettes de financement"),
    ("Actif_E2",       "Augmentation des dettes financières"),  # [EXT alias variante frequente]
    ("Actif_TOTAL_I",  "Total I A+B+C+D+E"),                      # [EXT]
    ("Actif_TOTAL_I",  "Actif immobilisé"),                       # [EXT alias convention CGNC alternative]
    ("Actif_F",        "Stocks"),
    ("Actif_F1",       "Marchandises"),
    ("Actif_F2",       "Matières et fournitures consommables"),
    ("Actif_F3",       "Produits en cours"),
    ("Actif_F4",       "Produits intermédiaires et produits résiduels"),
    ("Actif_F5",       "Produits finis"),
    ("Actif_G",        "Créances de l'actif circulant"),
    ("Actif_G1",       "Fournisseurs débiteurs, avances et acomptes"),
    ("Actif_G2",       "Clients et comptes rattachés"),
    ("Actif_G3",       "Personnel"),
    ("Actif_G4",       "Etat"),
    ("Actif_G5",       "Comptes d'associés"),
    ("Actif_G6",       "Autres débiteurs"),
    ("Actif_G7",       "Comptes de régularisation Actif"),
    ("Actif_H",        "Titres et valeurs de placement"),
    ("Actif_I",        "Ecarts de conversion - Actif éléments circulants"),
    ("Actif_TOTAL_II", "Total II F+G+H+I"),                       # [EXT]
    ("Actif_TOTAL_II", "Actif circulant hors trésorerie"),        # [EXT alias convention CGNC alternative]
    ("Actif_tresor",   "Trésorerie Actif"),
    ("Actif_tresor1",  "Chèques et valeurs à encaisser"),
    ("Actif_tresor2",  "Banques Trésorerie Générale et Chèques postaux"),
    ("Actif_tresor2",  "Banques T G et Chèques Postaux"),  # [EXT alias abréviation OCR fréquente "T.G & CP"]
    ("Actif_tresor2",  "Banques T G et C C P"),  # [EXT alias sigle "T.G. et C.C.P."]
    ("Actif_tresor3",  "Caisses régies d'avances et accréditifs"),
    ("Actif_tresor4",  "Provisions pour dépréciation des comptes de trésorerie"),  # [EXT: champ hors CIFEN standard mais recurrent]
    ("Actif_tresor",        "Total III"),                       # [EXT]
    ("Actif_TOTAL_GENERAL", "Total général I plus II plus III"),  # [EXT]
    ("Actif_TOTAL_GENERAL", "Total Actif"),                       # [EXT alias convention CGNC alternative]
]

# --- PASSIF -------------------------------------------------------------
PASSIF_FIELDS: List[Tuple[str, str]] = [
    ("Passif_A",            "Capitaux propres"),  # [EXT alias tete de section]
    ("Passif_A",            "Fonds propres"),      # [EXT alias tete de section, synonyme frequent]
    ("Passif_A2",           "Capital social ou personnel"),
    ("Passif_A_nonappele",  "Moins actionnaires capital souscrit non appelé"),  # [EXT]
    ("Passif_A6",           "Primes d'émission de fusion et d'apport"),
    ("Passif_A7",           "Ecarts de réévaluation"),
    ("Passif_A8",           "Réserve légale"),
    ("Passif_A9",           "Autres réserves"),
    ("Passif_A9",           "Réserves diverses"),  # [EXT alias variante frequente]
    ("Passif_A10",          "Report à nouveau"),
    ("Passif_A11",          "Résultats nets en instance d'affectation"),
    ("Passif_A12",          "Résultat net de l'exercice"),
    ("Passif_A",            "Total des capitaux propres"),
    ("Passif_B",            "Capitaux propres assimilés"),
    ("Passif_B1",           "Subventions d'investissement"),
    ("Passif_B2",           "Provisions réglementées"),
    ("Passif_C",            "Dettes de financement"),
    ("Passif_C1",           "Emprunts obligataires"),
    ("Passif_C2",           "Autres dettes de financement"),
    ("Passif_D",            "Provisions durables pour risques et charges"),
    ("Passif_D1",           "Provisions pour risques"),
    ("Passif_D2",           "Provisions pour charges"),
    ("Passif_E",            "Ecarts de conversion Passif"),
    ("Passif_E1",           "Augmentation des créances immobilisées"),
    ("Passif_E2",           "Diminution des dettes de financement"),
    ("Passif_E2",           "Diminution des dettes financières"),  # [EXT alias variante frequente]
    ("Passif_TOTAL_I",      "Total I A+B+C+D+E"),                 # [EXT]
    ("Passif_TOTAL_I",      "Financement permanent"),             # [EXT alias convention CGNC alternative]
    ("Passif_F",            "Dettes du passif circulant"),
    ("Passif_F1",           "Fournisseurs et comptes rattachés"),
    ("Passif_F2",           "Clients créditeurs avances et acomptes"),
    ("Passif_F3",           "Personnel"),
    ("Passif_F4",           "Organismes sociaux"),
    ("Passif_F5",           "Etat"),
    ("Passif_F6",           "Comptes d'associés"),
    ("Passif_F7",           "Autres créanciers"),
    ("Passif_F8",           "Comptes de régularisation Passif"),
    ("Passif_G",            "Autres provisions pour risques et charges"),
    ("Passif_H",            "Ecarts de conversion Passif éléments circulants"),
    ("Passif_H",            "Ecarts de conversion Passif"),  # [EXT alias: variante sans "elements circulants",
                                                              #  distinguee de Passif_E par l'ordre d'apparition]
    ("Passif_TOTAL_II",     "Total II F+G+H"),                    # [EXT]
    ("Passif_TOTAL_II",     "Passif circulant hors trésorerie"),  # [EXT alias convention CGNC alternative]
    ("Passif_TOTAL_II",     "Total Passif circulant"),            # [EXT alias variante frequente]
    ("Passif_tresor",       "Trésorerie Passif"),
    ("Passif_tresor1",      "Crédits d'escompte"),
    ("Passif_tresor2",      "Crédits de trésorerie"),
    ("Passif_tresor3",      "Banques soldes créditeurs"),
    ("Passif_tresor",           "Total III"),                    # [EXT]
    ("Passif_TOTAL_GENERAL",    "Total général I plus II plus III"),  # [EXT]
    ("Passif_TOTAL_GENERAL",    "Total Passif"),                      # [EXT alias convention CGNC alternative]
]

# --- CPC ------------------------------------------------------------------
CPC_FIELDS: List[Tuple[str, str]] = [
    ("CPC_I",      "Produits d'exploitation"),
    ("CPC_I_1",    "Ventes de marchandises en l'état"),
    ("CPC_I_2",    "Ventes de biens et services produits"),
    ("CPC_I_3",    "Chiffres d'affaires"),
    ("CPC_I_4",    "Variation des stocks de produits"),
    ("CPC_I_5",    "Immobilisations produites par l'entreprise pour elle même"),
    ("CPC_I_6",    "Subventions d'exploitation"),
    ("CPC_I_7",    "Autres produits d'exploitation"),
    ("CPC_I_8",    "Reprises d'exploitation transferts de charges"),
    ("CPC_I",      "Total I"),  # doublon volontaire : "Total I" == la rubrique I
    ("CPC_II",     "Charges d'exploitation"),
    ("CPC_II_1",   "Achats revendus de marchandises"),
    ("CPC_II_2",   "Achats consommés de matières et fournitures"),
    ("CPC_II_3",   "Autres charges externes"),
    ("CPC_II_4",   "Impôts et taxes"),
    ("CPC_II_5",   "Charges de personnel"),
    ("CPC_II_6",   "Autres charges d'exploitation"),
    ("CPC_II_7",   "Dotations d'exploitation"),
    ("CPC_II",     "Total II"),
    ("CPC_III",    "Résultat d'exploitation"),
    ("CPC_IV",     "Produits financiers"),
    ("CPC_IV_1",   "Produits des titres de participation et autres titres immobilisés"),
    ("CPC_IV_2",   "Gains de change"),
    ("CPC_IV_3",   "Intérêts et autres produits financiers"),
    ("CPC_IV_4",   "Reprises financières transferts de charges"),
    ("CPC_IV",     "Total IV"),
    ("CPC_V",      "Charges financières"),
    ("CPC_V_1",    "Charges d'intérêts"),
    ("CPC_V_2",    "Pertes de change"),
    ("CPC_V_3",    "Autres charges financières"),
    ("CPC_V_4",    "Dotations financières"),
    ("CPC_V",      "Total V"),
    ("CPC_VI",     "Résultat financier"),
    ("CPC_VII",    "Résultat courant"),
    ("CPC_VIII",   "Produits non courants"),
    ("CPC_VIII_1", "Produits des cessions d'immobilisations"),
    ("CPC_VIII_2", "Subventions d'équilibre"),
    ("CPC_VIII_3", "Reprises sur subventions d'investissement"),
    ("CPC_VIII_4", "Autres produits non courants"),
    ("CPC_VIII_5", "Reprises non courantes transferts de charges"),
    ("CPC_VIII",   "Total VIII"),
    ("CPC_IX",     "Charges non courantes"),
    ("CPC_IX_1",   "Valeurs nettes d'amortissements des immobilisations cédées"),
    ("CPC_IX_2",   "Subventions accordées"),
    ("CPC_IX_3",   "Autres charges non courantes"),
    ("CPC_IX_4",   "Dotations non courantes aux amortissements et aux provisions"),
    ("CPC_IX",     "Total IX"),
    ("CPC_X",      "Résultat non courant"),
    ("CPC_XI",     "Résultat avant impôts"),
    ("CPC_XII",    "Impôts sur les résultats"),
    ("CPC_XIII",   "Résultat net"),
    ("CPC_TOTAL_PRODUITS", "Total des produits I plus IV plus VIII"),  # [EXT]
    ("CPC_TOTAL_CHARGES",  "Total des charges II plus V plus IX plus XII"),  # [EXT]
    ("CPC_XIII",   "Résultat net total produits moins total charges"),
    ("CPC_XIV",    "Résultat par action"),  # [EXT: champ hors CIFEN standard mais recurrent]
]

SECTIONS = {
    "ACTIF":  ACTIF_FIELDS,
    "PASSIF": PASSIF_FIELDS,
    "CPC":    CPC_FIELDS,
}


def build_all_codes() -> List[str]:
    """Liste ordonnée et dédupliquée de TOUS les codes CIFEN (Actif+Passif+CPC),
    utilisée comme en-tête de colonnes pour le tableau large (data_cifen.csv /
    data_totale.csv)."""
    seen = set()
    codes: List[str] = []
    for section_fields in (ACTIF_FIELDS, PASSIF_FIELDS, CPC_FIELDS):
        for code, _ in section_fields:
            if code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


ALL_CIFEN_CODES: List[str] = build_all_codes()


# ======================================================================
# 2) NORMALISATION DE TEXTE + MATCHING FLOU (fuzzy), en 2 passes
# ======================================================================

ROMAN_TOKENS = {
    "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
    "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _strip_short_bracket_refs(t: str, open_ch: str, close_ch: str) -> str:
    """Supprime le contenu entre crochets/parenthèses UNIQUEMENT quand c'est une
    référence courte type "(A)", "(2)", "(I)" (simple lettre/chiffre/romain).
    Le contenu plus long est CONSERVÉ (juste les délimiteurs enlevés), car il porte
    souvent une info utile pour distinguer 2 champs proches, ex: "(A+B+C+D+E)" qui
    permet de différencier "Total I" de "Total II F+G+H+I", ou "(Éléments circulants)".
    """
    pattern = re.compile(re.escape(open_ch) + r"(.*?)" + re.escape(close_ch))

    def repl(m: "re.Match") -> str:
        inner_alnum = re.sub(r"[^a-z0-9]", "", m.group(1))
        if len(inner_alnum) <= 2:
            return " "
        return " " + m.group(1) + " "

    return pattern.sub(repl, t)


def normalize_label(text: str) -> str:
    """Normalise un libellé brut OCR pour le comparer à un libellé canonique CIFEN.

    Enlève : accents, flèches "→", numérotation romaine/arabe de tête ("I.", "12.",
    "VII :"), ponctuation, espaces multiples, caractères de rupture de tableau OCR
    (∥, |, •). Les parenthèses/crochets sont enlevés mais leur contenu n'est
    supprimé QUE s'il s'agit d'une courte référence (une lettre/chiffre) -- le
    contenu plus long (souvent une formule ou une précision utile) est conservé.
    Les sigles à points ("T.G.", "C.C.P.") sont recollés en un seul bloc ("tg",
    "ccp") avant comparaison, car une fois éclatés en lettres isolées par la
    ponctuation ils ne ressemblent plus du tout à leur équivalent en toutes
    lettres dans le dictionnaire.
    """
    if text is None:
        return ""
    t = strip_accents(text).lower()
    t = t.replace("→", " ").replace("∥", " ").replace("|", " ")
    t = _strip_short_bracket_refs(t, "(", ")")
    t = _strip_short_bracket_refs(t, "[", "]")
    t = re.sub(r"[^a-z0-9\s]", " ", t)  # ponctuation, *, :, ., etc -> espace
    t = re.sub(r"\s+", " ", t).strip()

    # recolle les runs de lettres isolees (sigles eclates par le retrait de la
    # ponctuation, ex: "t g" -> "tg", "c c p" -> "ccp")
    words = t.split(" ")
    merged: List[str] = []
    i = 0
    while i < len(words):
        if len(words[i]) == 1 and words[i].isalpha():
            run = [words[i]]
            j = i + 1
            while j < len(words) and len(words[j]) == 1 and words[j].isalpha():
                run.append(words[j])
                j += 1
            merged.append("".join(run))
            i = j
        else:
            merged.append(words[i])
            i += 1
    words = merged

    # enlève les tokens de numérotation en tête de ligne (romains ou chiffres)
    while words and (words[0] in ROMAN_TOKENS or words[0].isdigit()):
        words.pop(0)
    t = " ".join(words).strip()
    return t


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    score = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        score = max(score, 0.9)
    return score


MATCH_THRESHOLD = 0.5      # score minimal pour accepter un match en passe 2
HIGH_CONFIDENCE = 0.90     # score au-delà duquel on valide un match direct en passe 1,
                           # peu importe la position dans la liste
MIN_MARGIN = 0.06          # écart minimal exigé entre le 1er et le 2e candidat en passe 2
LOOKAHEAD = 6              # fenêtre de recherche "normale" autour du pointeur en passe 2
LOOKAHEAD_RECOVERY = 14    # fenêtre élargie si rien de valable dans la fenêtre normale
                           # (permet de rattraper un pointeur resté en retard/avance)
LOW_CONFIDENCE_REPORT = 0.80  # en-dessous de ce score, la ligne mappée est quand même
                               # listée dans _matches_incertains.csv pour audit manuel


def align_rows_to_fields(
    raw_labels: List[str], canonical: List[Tuple[str, str]]
) -> List[Tuple[int, Optional[int], float]]:
    """Aligne les libellés OCR bruts sur la liste canonique CIFEN, en 2 passes,
    de façon robuste aux lignes ratées / fusionnées (pas de "pointeur strict" qui
    ferait dériver toute la suite d'une section en cas d'erreur locale).

    Retourne une liste de tuples (index_raw, index_canonical_ou_None, score).
    index_canonical_ou_None = None si aucune correspondance suffisamment fiable
    n'a été trouvée (ligne à vérifier manuellement -> _non_mappes.csv), PLUTÔT
    que de deviner et risquer une valeur silencieusement fausse.
    """
    n_raw = len(raw_labels)
    n_canon = len(canonical)
    norm_canon = [normalize_label(lbl) for _, lbl in canonical]
    norm_raw_list = [normalize_label(r) for r in raw_labels]

    # pré-calcule, pour chaque ligne brute, les scores contre TOUTE la liste canonique
    # (trié du meilleur au moins bon), une seule fois.
    candidates: List[List[Tuple[int, float]]] = []
    for norm_raw in norm_raw_list:
        if not norm_raw:
            candidates.append([])
            continue
        scored = [(j, similarity(norm_raw, norm_canon[j])) for j in range(n_canon)]
        scored.sort(key=lambda x: -x[1])
        candidates.append(scored)

    canon_used = [False] * n_canon
    raw_assigned: List[Optional[int]] = [None] * n_raw
    raw_score: List[float] = [0.0] * n_raw

    # ---- PASSE 1 : matches quasi certains, indépendants de la position ----
    # Assignation gloutonne globale : on trie TOUTES les paires (ligne, champ) à
    # haute confiance par score décroissant, et on les valide tant que la ligne
    # et le champ visés sont encore libres. Ça plante des "ancres" fiables un peu
    # partout dans la section, ce qui empêche un décalage local de se propager.
    high_conf_pairs = []
    for i, scored in enumerate(candidates):
        for j, s in scored:
            if s >= HIGH_CONFIDENCE:
                high_conf_pairs.append((s, i, j))
    high_conf_pairs.sort(key=lambda x: -x[0])
    for s, i, j in high_conf_pairs:
        if raw_assigned[i] is None and not canon_used[j]:
            raw_assigned[i] = j
            raw_score[i] = s
            canon_used[j] = True

    # ---- PASSE 2 : matches positionnels avec marge de sécurité ----
    pointer = 0
    for i in range(n_raw):
        if raw_assigned[i] is not None:
            pointer = max(pointer, raw_assigned[i] + 1)
            continue
        if not norm_raw_list[i]:
            continue

        def window_candidates(width: int):
            return [
                (j, s) for j, s in candidates[i]
                if not canon_used[j] and pointer <= j < pointer + width
            ]

        wc = window_candidates(LOOKAHEAD)
        if not wc:
            wc = window_candidates(LOOKAHEAD_RECOVERY)
        wc.sort(key=lambda x: -x[1])

        if wc:
            best_j, best_s = wc[0]
            second_s = wc[1][1] if len(wc) > 1 else 0.0
            if best_s >= MATCH_THRESHOLD and (best_s - second_s) >= MIN_MARGIN:
                raw_assigned[i] = best_j
                raw_score[i] = best_s
                canon_used[best_j] = True
                pointer = best_j + 1
            # sinon : match trop ambigu (2 champs se ressemblent trop) -> on laisse
            # non mappé plutôt que de deviner (ex: "Autres produits non courants"
            # vs "Autres charges non courantes").

    results: List[Tuple[int, Optional[int], float]] = []
    for i in range(n_raw):
        if raw_assigned[i] is not None:
            results.append((i, raw_assigned[i], round(raw_score[i], 3)))
        else:
            best_guess_score = candidates[i][0][1] if candidates[i] else 0.0
            results.append((i, None, round(best_guess_score, 3)))
    return results


# ======================================================================
# 3) PARSING DES NOMBRES (formats FR marocains : espace ou point milliers,
#    virgule décimale ; parfois notation US résiduelle)
# ======================================================================

def parse_number(raw: str) -> Optional[float]:
    if raw is None:
        return None
    s = raw.strip().replace("\xa0", "").replace(" ", "")
    if s in ("", "-", "--", "."):
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    if s.startswith("-"):
        negative = True
        s = s[1:]

    has_comma = "," in s
    has_dot = "." in s

    if has_comma and has_dot:
        # le dernier séparateur rencontré = décimale
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        # virgule = décimale (format FR standard)
        s = s.replace(",", ".")
    elif has_dot:
        # ambigu : si un seul point et exactement 2 décimales -> décimale US
        # sinon (plusieurs points, ou pas 2 chiffres après) -> séparateur milliers
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            pass  # déjà au bon format (point décimal)
        else:
            s = s.replace(".", "")

    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


# ======================================================================
# 4) LECTURE DES CSV DOCLING
# ======================================================================

def find_csv_file(entreprise_dir: str, annee, filename: str, tables_subdir: str) -> Optional[str]:
    """Cherche filename d'abord au chemin standard, sinon en fallback récursif
    sous docling_result/ (au cas où le sous-dossier tables_csv n'existe pas)."""
    base = os.path.join(entreprise_dir, str(annee), "docling_result")
    standard_path = os.path.join(base, tables_subdir, filename)
    if os.path.isfile(standard_path):
        return standard_path

    if os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f.lower() == filename.lower():
                    return os.path.join(root, f)
    return None


def read_csv_rows(path: str) -> List[List[str]]:
    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter=";", quotechar='"')
        for row in reader:
            if any(cell.strip() for cell in row):
                rows.append(row)
    return rows


# ======================================================================
# 5) DETECTION DU NOMBRE DE COLONNES DE VALEURS + EXTRACTION
# ======================================================================

# (la colonne "Verification" du CSV source n'est plus lue : elle a ete corrigee
# et validee manuellement par l'utilisateur, donc son contenu n'a plus de sens
# a interpreter automatiquement -- on la traite comme une colonne ignoree, au
# meme titre qu'elle soit presente, absente, vide ou remplie sur une ligne.)


@dataclass
class ExtractedField:
    original_label: str
    code: str
    reference_label: str
    match_score: float
    value_current: Optional[float]
    value_previous: Optional[float]


def detect_value_col_count(rows: List[List[str]]) -> int:
    """Nombre de colonnes de valeurs (hors 1ère colonne = libellé),
    en se basant sur la ligne la plus fréquente (hors ligne d'en-tête)."""
    lengths = [len(r) - 1 for r in rows if len(r) > 1]
    if not lengths:
        return 0
    counts: Dict[int, int] = {}
    for l in lengths:
        counts[l] = counts.get(l, 0) + 1
    return max(counts, key=counts.get)


# mots-cles pour reperer une ligne-titre parasite (2e ligne d'en-tete en plus de
# la vraie, ex: "PASSIF / KDH", "BILAN ACTIF (en KDH)") qui aurait echappe a la
# detection normale. Exige un mot de SECTION *et* une unite monetaire, ET aucune
# valeur numerique sur la ligne -- pour ne jamais confondre avec un vrai champ
# comme "Capitaux propres" ou "Comptes de regularisation Actif" (qui n'ont pas
# d'unite monetaire dans leur libelle).
SECTION_TITLE_TOKENS = ("actif", "passif", "bilan", "cpc")
UNIT_HINT_TOKENS = ("kdh", "koh", "mad", "dhs", "dh")


def _looks_like_parasite_title_row(row: List[str]) -> bool:
    label_norm = normalize_label(row[0])
    if not label_norm:
        return False
    words = label_norm.split(" ")
    has_section_word = any(tok in words for tok in SECTION_TITLE_TOKENS)
    has_unit_word = any(tok in words for tok in UNIT_HINT_TOKENS)
    all_values_empty = not any(c.strip() for c in row[1:])
    return has_section_word and has_unit_word and all_values_empty


def extract_section(
    section_name: str, rows: List[List[str]]
) -> Tuple[List[ExtractedField], List[str]]:
    """Extrait les champs (mappés CIFEN) d'une section (ACTIF/PASSIF/CPC).
    Retourne (champs extraits, libellés non mappés).

    NOTE : la colonne "Verification" du CSV source (5e colonne, quand présente)
    n'est PAS lue -- son contenu a été corrigé/validé manuellement en amont et
    n'a plus de signification à interpréter automatiquement. Une ligne est
    traitée exactement de la même façon que cette colonne soit présente,
    absente, vide ou remplie."""
    if not rows:
        return [], []

    header_hints = ("brut", "net", "exercice", "operations", "designation",
                     "nature", "totaux", "amort", "elements", "rubrique", "col")
    data_rows = rows
    # jusqu'a 2 lignes d'en-tete/titre parasites en tete de fichier (ex: titre
    # "PASSIF / KDH" ou vraie ligne d'en-tete "EXERCICE"/"EXERCICE PRECEDENT",
    # dans un ordre ou dans l'autre). Les 2 verifications sont volontairement
    # distinctes : header_hints ne contient AUCUN mot pouvant apparaitre dans un
    # vrai champ (ex: pas "propres", qui casserait "Capitaux propres"/"Fonds
    # propres"), donc rejouable sans risque ; le check "titre parasite" exige en
    # plus un mot de section + une unite monetaire + aucune valeur sur la ligne.
    for _ in range(2):
        if not data_rows:
            break
        first_norm = normalize_label(" ".join(data_rows[0]))
        if any(h in first_norm for h in header_hints):
            data_rows = data_rows[1:]
        elif _looks_like_parasite_title_row(data_rows[0]):
            data_rows = data_rows[1:]
        else:
            break

    n_val_cols = detect_value_col_count(data_rows)

    if section_name == "ACTIF":
        if n_val_cols in (4, 5):
            mode = "full"       # brut, amort, net, netN-1, [verif]
        elif n_val_cols in (2, 3):
            mode = "simple"     # net, netN-1, [verif]  (format banque)
        else:
            mode = "unknown"
    elif section_name == "PASSIF":
        mode = "simple" if n_val_cols in (2, 3) else "unknown"
    elif section_name == "CPC":
        if n_val_cols in (4, 5):
            mode = "full"
        elif n_val_cols in (2, 3):
            mode = "simple"
        else:
            mode = "unknown"
    else:
        mode = "unknown"

    raw_labels = [r[0] for r in data_rows]
    canonical = SECTIONS[section_name]
    alignment = align_rows_to_fields(raw_labels, canonical)

    extracted: List[ExtractedField] = []
    unmapped: List[str] = []

    for (i, canon_idx, score), row in zip(alignment, data_rows):
        label = row[0].strip()
        if not label:
            continue

        cells = row[1:]
        val_current, val_previous = None, None

        if mode == "full":
            # cells = [brut, amort, net, netN-1, (verification -- ignoree)]
            if len(cells) >= 3:
                val_current = parse_number(cells[2])
            if len(cells) >= 4:
                val_previous = parse_number(cells[3])
        elif mode == "simple":
            # cells = [net, netN-1, (verification -- ignoree)]
            if len(cells) >= 1:
                val_current = parse_number(cells[0])
            if len(cells) >= 2:
                val_previous = parse_number(cells[1])

        if canon_idx is None:
            unmapped.append(label)
            continue

        code, ref_label = canonical[canon_idx]
        extracted.append(
            ExtractedField(
                original_label=label,
                code=code,
                reference_label=ref_label,
                match_score=score,
                value_current=val_current,
                value_previous=val_previous,
            )
        )

    return extracted, unmapped


def read_report_sections(
    entreprise_dir: str, annee, tables_subdir: str, log_errors: bool = True, entreprise: str = ""
) -> Tuple[Optional[Dict[str, Tuple[List[ExtractedField], List[str]]]], List[str]]:
    """Lit et extrait les 3 sections (ACTIF/PASSIF/CPC) pour UNE annee donnée.

    Si `log_errors` est False, l'absence de fichier n'est PAS considérée comme une
    erreur (utilisé pour la tentative "opportuniste" de lecture d'un vrai rapport
    pour une année dérivée, où il est normal que le rapport n'existe pas toujours).
    Retourne (None, []) si AUCUN des 3 fichiers n'a été trouvé.
    """
    result: Dict[str, Tuple[List[ExtractedField], List[str]]] = {}
    erreurs: List[str] = []
    any_found = False

    for section_name, filename in FILES_BY_SECTION.items():
        path = find_csv_file(entreprise_dir, annee, filename, tables_subdir)
        if path is None:
            if log_errors:
                msg = f"[{entreprise}] {section_name} introuvable pour l'annee {annee}"
                print("  !! " + msg)
                erreurs.append(msg)
            result[section_name] = ([], [])
            continue
        any_found = True
        try:
            rows = read_csv_rows(path)
            extracted, unmapped = extract_section(section_name, rows)
            result[section_name] = (extracted, unmapped)
        except Exception as exc:  # on ne casse jamais tout le run
            msg = f"[{entreprise}] Erreur lecture {section_name} annee {annee}: {exc}"
            print("  !! " + msg)
            erreurs.append(msg)
            result[section_name] = ([], [])

    if not any_found:
        return None, erreurs
    return result, erreurs


# ======================================================================
# 6) PLANIFICATION DES ANNEES (ancre + dérivation N-1)
# ======================================================================

@dataclass
class YearPlan:
    annee: int
    source: str            # "rapport" (ouvert sur disque) ou "derive" (via N-1 d'une autre annee)
    depuis_annee: Optional[int] = None  # si derive: annee du rapport source
    demandee: bool = True   # False si l'annee est un "bonus" recupere gratuitement


def planifier_annees(annees_demandees: List[int]) -> List[YearPlan]:
    """Planifie quels rapports ouvrir sur disque et quelles annees en derivent.

    REGLE (mise a jour) : CHAQUE annee explicitement demandee est TOUJOURS une
    ancre -> son PROPRE vrai rapport est ouvert sur le disque, meme si elle est
    immediatement consecutive a une autre annee demandee. Ex: si 2021 ET 2020
    sont tous les deux demandes, les DEUX rapports reels 2021/ et 2020/ sont
    ouverts (on ne derive JAMAIS une annee demandee depuis une autre, meme
    voisine) -> "2022 EXISTE (dans la liste) -> on extrait du RAPPORT 2022,
    pas de 2023".

    En complement, CHAQUE ancre (donc chaque annee demandee) essaie de recuperer
    GRATUITEMENT l'annee immediatement precedente via sa colonne "Net N-1" --
    mais SEULEMENT si cette annee precedente n'est pas deja couverte par
    ailleurs (ni elle-meme demandee/ancre, ni deja recuperee comme bonus par
    une ancre plus proche/plus grande). On traite les ancres de la plus grande
    a la plus petite annee pour que ce soit toujours l'ancre la PLUS PROCHE qui
    "gagne" un ecart entre deux annees demandees non consecutives.

    LIMITE INHERENTE : un bilan n'a que 2 colonnes de valeurs (Net et Net N-1)
    -> on ne peut JAMAIS recuperer plus d'UNE annee en arriere par ancre. Si
    l'ecart entre 2 annees demandees est de 2 ans ou plus (ex: 2025 et 2022 ->
    il manque 2024 ET 2023), seule l'annee immediatement precedente (2024) est
    recuperee gratuitement depuis le rapport 2025 -- l'annee encore avant
    (2023) reste manquante, SAUF si elle est elle-meme demandee explicitement
    (auquel cas ce sera sa propre ancre, cf regle ci-dessus).
    """
    demandees = set(annees_demandees)
    couvertes: Dict[int, YearPlan] = {}

    # 1) chaque annee demandee est TOUJOURS sa propre ancre (vrai rapport ouvert)
    for annee in demandees:
        couvertes[annee] = YearPlan(annee=annee, source="rapport", demandee=True)

    # 2) pour chaque ancre (de la plus grande a la plus petite), recupere l'annee
    #    N-1 gratuitement SI elle n'est pas deja couverte
    for annee in sorted(demandees, reverse=True):
        precedente = annee - 1
        if precedente not in couvertes:
            couvertes[precedente] = YearPlan(
                annee=precedente,
                source="derive",
                depuis_annee=annee,
                demandee=(precedente in demandees),  # en pratique toujours False ici,
                # puisque si "precedente" etait demandee elle serait deja sa propre
                # ancre via l'etape 1) et n'entrerait jamais dans cette branche.
            )

    return sorted(couvertes.values(), key=lambda p: p.annee, reverse=True)


# ======================================================================
# 7) FUSION / ECRITURE DES CSV DE SORTIE (idempotent par clé)
# ======================================================================

def merge_and_write(path: str, fieldnames: List[str], new_rows: List[dict], key_cols=("Bilan", "Annee")):
    """Fusionne new_rows dans le fichier existant à `path`, en remplaçant
    UNIQUEMENT les lignes dont la clé (key_cols) correspond à une ligne de
    new_rows. Les autres lignes déjà présentes (autres entreprises / autres
    années / autres bilans) sont conservées telles quelles.

    MIGRATION DE SCHEMA : si le fichier existant a été écrit avec un schéma de
    colonnes différent (ex: ancien format long vs nouveau format tableau large),
    on ne fusionne pas ligne à ligne -> on régénère proprement avec le nouveau
    schéma au lieu de planter, et on prévient clairement l'utilisateur."""
    existing_rows = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh, delimiter=";")
            ancien_entete = reader.fieldnames or []
            if set(ancien_entete) != set(fieldnames):
                print(f"  !! ATTENTION : '{path}' a un ancien format de colonnes (probablement "
                      f"une version précédente du script). Il est régénéré avec le nouveau format "
                      f"(rien n'est perdu ailleurs, mais relance toutes les entreprises que tu veux "
                      f"revoir dans ce fichier précis).")
                existing_rows = []
            else:
                existing_rows = list(reader)

    keys_being_replaced = {tuple(r.get(k, "") for k in key_cols) for r in new_rows}
    kept = [
        r for r in existing_rows
        if tuple(r.get(k, "") for k in key_cols) not in keys_being_replaced
    ]

    all_rows = kept + new_rows
    all_rows.sort(key=lambda r: tuple(r.get(k, "") for k in key_cols))

    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(all_rows)


def format_value(v: Optional[float]) -> str:
    return "" if v is None else f"{v:.2f}"


# ======================================================================
# 8) TRAITEMENT D'UNE ENTREPRISE
# ======================================================================

FILES_BY_SECTION = {
    "ACTIF":  "bilan_actif.csv",
    "PASSIF": "bilan_passif.csv",
    "CPC":    "cpc.csv",
}


def process_entreprise(
    entreprise: str,
    annees_demandees: List[int],
    root: str = "output",
    tables_subdir: str = "tables_csv",
    totale_path: str = "data_totale.csv",
):
    entreprise_dir = os.path.join(root, entreprise)
    plan = planifier_annees(annees_demandees)

    print(f"\n=== {entreprise} ===")
    for p in plan:
        if p.source == "rapport":
            print(f"  {p.annee} -> lecture du rapport {p.annee}/")
        else:
            bonus = "" if p.demandee else "  [BONUS, non demandée]"
            print(f"  {p.annee} -> dérivé de la colonne N-1 du rapport {p.depuis_annee}/ (pas de lecture disque){bonus}")

    complet_rows: List[dict] = []
    verification_rows: List[dict] = []
    non_mappes_rows: List[dict] = []
    incertains_rows: List[dict] = []
    erreurs: List[str] = []

    pivot: Dict[Tuple[str, str], Dict[str, str]] = {}

    cache_sections: Dict[int, Dict[str, Tuple[List[ExtractedField], List[str]]]] = {}
    cache_real_reports: Dict[int, Optional[Dict[str, Tuple[List[ExtractedField], List[str]]]]] = {}

    for p in plan:
        source_annee = p.annee if p.source == "rapport" else p.depuis_annee

        if source_annee not in cache_sections:
            sections, errs = read_report_sections(
                entreprise_dir, source_annee, tables_subdir, log_errors=True, entreprise=entreprise
            )
            erreurs.extend(errs)
            cache_sections[source_annee] = sections if sections is not None else {
                s: ([], []) for s in FILES_BY_SECTION
            }

        for section_name in FILES_BY_SECTION:
            extracted, unmapped = cache_sections[source_annee][section_name]

            if p.source == "rapport":
                value_getter = lambda f: f.value_current
            else:
                value_getter = lambda f: f.value_previous

            pivot_key = (entreprise, str(p.annee))
            pivot.setdefault(pivot_key, {})

            for f in extracted:
                value = value_getter(f)
                complet_rows.append({
                    "Bilan": section_name,
                    "Champ_Original": f.original_label,
                    "Annee": str(p.annee),
                    "Valeur": format_value(value),
                })
                pivot[pivot_key][f.code] = format_value(value)

                # uniquement pour l'année "ancre" (le score de match ne dépend pas
                # de derive/rapport, pas la peine de le lister 2 fois)
                if p.source == "rapport" and f.match_score < LOW_CONFIDENCE_REPORT:
                    incertains_rows.append({
                        "Bilan": section_name,
                        "Annee": str(p.annee),
                        "Champ_Original": f.original_label,
                        "Code_CIFEN": f.code,
                        "Libelle_Reference": f.reference_label,
                        "Score": f"{f.match_score:.3f}",
                    })

            if p.source == "rapport":
                for lbl in unmapped:
                    non_mappes_rows.append({
                        "Bilan": section_name,
                        "Annee": str(p.annee),
                        "Champ_Original_Non_Mappe": lbl,
                    })

        # ---- Vérification des années dérivées contre un vrai rapport, s'il existe ----
        if p.source == "derive":
            if p.annee not in cache_real_reports:
                real_sections, _errs = read_report_sections(
                    entreprise_dir, p.annee, tables_subdir, log_errors=False, entreprise=entreprise
                )
                cache_real_reports[p.annee] = real_sections

            real_sections = cache_real_reports[p.annee]
            if real_sections is not None:
                for section_name in FILES_BY_SECTION:
                    derived_extracted, _ = cache_sections[source_annee][section_name]
                    real_extracted, _ = real_sections[section_name]
                    real_by_code = {f.code: f.value_current for f in real_extracted}

                    for f in derived_extracted:
                        derived_value = f.value_previous
                        real_value = real_by_code.get(f.code)
                        if derived_value is None and real_value is None:
                            continue
                        ecart = None
                        if derived_value is not None and real_value is not None:
                            ecart = round(derived_value - real_value, 2)
                        verification_rows.append({
                            "Entreprise": entreprise,
                            "Bilan": section_name,
                            "Code_CIFEN": f.code,
                            "Annee": str(p.annee),
                            "Valeur_Derivee_N1": format_value(derived_value),
                            "Valeur_Rapport_Reel": format_value(real_value),
                            "Ecart": "" if ecart is None else f"{ecart:.2f}",
                            "Libelle_Reference": f.reference_label,
                        })

    pivot_rows: List[dict] = []
    for (ent, annee_str), code_values in pivot.items():
        row = {"Entreprise": ent, "Annee": annee_str}
        for code in ALL_CIFEN_CODES:
            row[code] = code_values.get(code, "")
        pivot_rows.append(row)

    complet_path = os.path.join(entreprise_dir, "data_complet.csv")
    cifen_path = os.path.join(entreprise_dir, "data_cifen.csv")
    verification_path = os.path.join(entreprise_dir, "data_verification.csv")
    non_mappes_path = os.path.join(entreprise_dir, "_non_mappes.csv")
    incertains_path = os.path.join(entreprise_dir, "_matches_incertains.csv")
    erreurs_path = os.path.join(entreprise_dir, "_erreurs.log")

    pivot_fieldnames = ["Entreprise", "Annee"] + ALL_CIFEN_CODES

    merge_and_write(complet_path, ["Bilan", "Champ_Original", "Annee", "Valeur"], complet_rows)
    merge_and_write(cifen_path, pivot_fieldnames, pivot_rows, key_cols=("Entreprise", "Annee"))
    merge_and_write(totale_path, pivot_fieldnames, pivot_rows, key_cols=("Entreprise", "Annee"))

    if verification_rows:
        merge_and_write(
            verification_path,
            ["Entreprise", "Bilan", "Code_CIFEN", "Annee", "Valeur_Derivee_N1", "Valeur_Rapport_Reel", "Ecart", "Libelle_Reference"],
            verification_rows,
            key_cols=("Entreprise", "Bilan", "Code_CIFEN", "Annee"),
        )
        print(f"  -> {verification_path}  ({len(verification_rows)} lignes : dérivé vs rapport réel)")

    os.makedirs(entreprise_dir, exist_ok=True)
    with open(non_mappes_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Bilan", "Annee", "Champ_Original_Non_Mappe"], delimiter=";")
        writer.writeheader()
        writer.writerows(non_mappes_rows)
    if non_mappes_rows:
        print(f"  ATTENTION: {len(non_mappes_rows)} ligne(s) non mappée(s) -> voir {non_mappes_path}")
    else:
        print(f"  -> {non_mappes_path}  (vide : tout est mappé)")

    os.makedirs(entreprise_dir, exist_ok=True)
    with open(incertains_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["Bilan", "Annee", "Champ_Original", "Code_CIFEN", "Libelle_Reference", "Score"], delimiter=";"
        )
        writer.writeheader()
        writer.writerows(incertains_rows)
    if incertains_rows:
        print(f"  ATTENTION: {len(incertains_rows)} correspondance(s) à faible confiance -> voir {incertains_path}")
    else:
        print(f"  -> {incertains_path}  (vide : aucune correspondance à faible confiance)")

    if erreurs:
        os.makedirs(entreprise_dir, exist_ok=True)
        with open(erreurs_path, "a", encoding="utf-8") as fh:
            for e in erreurs:
                fh.write(e + "\n")

    print(f"  -> {complet_path}")
    print(f"  -> {cifen_path}  (tableau large: {len(pivot_rows)} ligne(s))")
    print(f"  -> {totale_path}  (mis à jour pour {entreprise} uniquement, les autres entreprises sont conservées)")


# ======================================================================
# 9) MODE JOURNAL (plusieurs entreprises en un seul run)
# ======================================================================

def process_journal(journal_path: str, root: str, tables_subdir: str, totale_path: str):
    with open(journal_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        for row in reader:
            if not row or not row[0].strip():
                continue
            entreprise = row[0].strip()
            if len(row) < 2 or not row[1].strip():
                continue
            annees = [int(a.strip()) for a in row[1].split(",") if a.strip()]
            if not annees:
                continue
            process_entreprise(entreprise, annees, root=root, tables_subdir=tables_subdir, totale_path=totale_path)


# ======================================================================
# 10) CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Extraction CIFEN (ACTIF/PASSIF/CPC) depuis CSV docling")
    parser.add_argument("entreprise", nargs="?", help="Nom exact du dossier entreprise (ex: afma_SA)")
    parser.add_argument("annees", nargs="*", type=int, help="Liste des annees a traiter (ex: 2016 2017 2025)")
    parser.add_argument("--journal", help="Fichier CSV 'entreprise;annees' pour traiter plusieurs entreprises d'un coup")
    parser.add_argument("--root", default="output", help="Dossier racine (defaut: output)")
    parser.add_argument("--tables-subdir", default="tables_csv", help="Sous-dossier des csv docling (defaut: tables_csv)")
    parser.add_argument(
        "--totale-path",
        default="data_totale.csv",
        help="Chemin du fichier cumulatif global 'tableau large' (defaut: data_totale.csv, a la racine du projet)",
    )
    args = parser.parse_args()

    if args.journal:
        process_journal(args.journal, root=args.root, tables_subdir=args.tables_subdir, totale_path=args.totale_path)
    elif args.entreprise and args.annees:
        process_entreprise(
            args.entreprise, args.annees, root=args.root, tables_subdir=args.tables_subdir, totale_path=args.totale_path
        )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()