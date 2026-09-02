#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mineru_extract_tables.py
=========================================================================
SCRIPT 1 du pipeline Document AI - Observatoire Marocain de la TPME
=========================================================================

Rôle dans le pipeline :

    PDF ──► [Script 1: mineru_extract_tables.py] ──► images PNG des
    tableaux financiers pertinents (+ JSON de traçabilité)
    ──► Script 2 (Docling) ──► Script 3 (extraction champs) ──► CSV

Ce script NE fait PAS de localisation de tableaux (pas de PyMuPDF, pas
de bbox). Il s'appuie entièrement sur les tableaux déjà détectés par
MinerU (content_list.json : image, HTML, caption, footnote, page) et se
concentre sur une tâche unique : décider intelligemment, parmi tous les
tableaux détectés, lesquels correspondent à Identification, Bilan Actif,
Bilan Passif et CPC - en ne conservant qu'une seule série cohérente
(comptes sociaux OU comptes consolidés) lorsque le rapport en contient
plusieurs.

Usage :
    python mineru_extract_tables.py --pdf rapport.pdf
    python mineru_extract_tables.py --pdf rapport.pdf --serie-preference consolide
    python mineru_extract_tables.py --pdf rapport.pdf --skip-mineru --mineru-output out/

Sortie :
    <output_dir>/<pdf_stem>_tables_analysis.json   (JSON riche, cf. spec)
    <output_dir>/selected_tables/identification.png
    <output_dir>/selected_tables/bilan_actif.png
    <output_dir>/selected_tables/bilan_passif.png
    <output_dir>/selected_tables/cpc.png

Auteur : CHAIMAA BENRADOUAN - Document AI / OCR / MinerU / Docling
=========================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# -------------------------------------------------------------------------
# Dépendance optionnelle : Pillow, pour livrer systématiquement des PNG
# dans selected_tables/ même si l'image source MinerU est un .jpg.
# Le script reste fonctionnel sans Pillow (simple copie, extension d'origine
# conservée) car on ne veut pas bloquer un pipeline industriel sur une
# dépendance non critique.
# -------------------------------------------------------------------------
try:
    from PIL import Image  # type: ignore
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# =========================================================================
# 1. LOGGING
# =========================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mineru_extract_tables")


# =========================================================================
# 2. CONFIGURATION MÉTIER - DICTIONNAIRES DE MOTS-CLÉS PONDÉRÉS
# =========================================================================
#
# Chaque dictionnaire associe une expression-clé (déjà normalisée : sans
# accents, minuscules) à un poids. Le score brut d'une catégorie pour un
# tableau donné est la somme des poids des expressions trouvées dans le
# texte du tableau (HTML aplati + caption + footnote), plafonnée à 100.
#
# Les poids ont été choisis pour refléter la spécificité du signal :
#   - une rubrique comptable très caractéristique (ex: "tresorerie actif")
#     a un poids élevé,
#   - une rubrique ambiguë / partagée entre catégories (ex: "capital
#     social" qui apparaît en Identification ET en Bilan Passif) a un
#     poids modéré pour éviter qu'elle ne décide seule de la classe,
#   - un mot très générique (ex: "actif") a un poids faible : il ne sert
#     que d'appoint.
# =========================================================================

# NOTE SUR LA NORMALISATION : le texte des tableaux est normalisé par
# normalize_text() qui minuscule, retire les accents ET retire toute
# ponctuation (apostrophes, virgules, tirets...). Les phrases-clés
# ci-dessous doivent donc être écrites SANS ponctuation
# (ex: "chiffre d affaires" et non "chiffre d'affaires").
#
# Les dictionnaires ci-dessous reprennent la nomenclature CGNC (Plan
# Comptable Général Marocain) : rubriques d'Identification, du Bilan
# Actif, du Bilan Passif et du CPC. Les intitulés de rubriques
# structurantes (postes principaux, totaux) ont un poids élevé ; les
# sous-rubriques de détail ont un poids modéré, et les termes trop
# génériques ou partagés entre catégories (ex: "personnel", "etat",
# "resultat net") ont un poids faible pour ne pas biaiser le score à
# eux seuls.

KEYWORDS_IDENTIFICATION: dict[str, int] = {
    "numero de registre du commerce et code du centre de registre du commerce": 22,
    "code du centre de registre du commerce": 16,
    "numero de registre du commerce": 18,
    "registre du commerce": 16,
    "nom de l entreprise": 16,
    "identifiant commun de l entreprise": 22,
    "ice": 14,
    "raison sociale": 20,
    "denomination sociale": 18,
    "denomination": 9,
    "siege social": 18,
    "adresse du siege": 10,
    "forme juridique": 12,
    "capital social": 8,
    "activite principale": 10,
    "secteur d activite": 10,
    "objet social": 10,
    "date de constitution": 12,
    "exercice social": 6,
    "numero d identification fiscale": 14,
    "identifiant fiscal": 12,
    "patente": 10,
    "cnss": 8,
}

KEYWORDS_BILAN_ACTIF: dict[str, int] = {
    # Postes structurants / totaux
    "actif immobilise": 18,
    "immobilisations en non valeur": 16,
    "immobilisations incorporelles": 15,
    "immobilisations corporelles": 15,
    "immobilisations financieres": 15,
    "actif circulant": 16,
    "creances de l actif circulant": 16,
    "tresorerie actif": 22,
    # FIX : la nomenclature CGNC marocaine écrit quasi toujours le total
    # général avec "DE L'" ("TOTAL DE L'ACTIF"), jamais "TOTAL ACTIF" seul.
    # L'ancienne clé "total actif" ne matchait donc presque jamais après
    # normalisation ("total de l actif" != "total actif" en sous-chaîne).
    # On couvre toutes les variantes OCR plausibles, poids le plus fort sur
    # la forme réellement observée.
    "total actif": 10,
    "total de l actif": 28,
    "total general de l actif": 26,
    "total general actif": 24,
    "actif net total": 14,
    "stocks": 8,
    "immobilisations": 6,
    "actif": 4,
    # Sous-rubriques Immobilisations en non valeur
    "frais preliminaires": 6,
    "charges a repartir sur plusieurs exercices": 6,
    "primes de remboursement des obligations": 6,
    # Sous-rubriques Immobilisations incorporelles
    "immobilisation en recherche et developpement": 6,
    "brevets marques droits et valeurs similaires": 6,
    "fonds commercial": 6,
    "autres immobilisations incorporelles": 5,
    # Sous-rubriques Immobilisations corporelles
    "terrains": 5,
    "constructions": 5,
    "installations techniques materiel et outillage": 7,
    "materiel de transport": 5,
    "mobilier materiel de bureau et amenagements divers": 7,
    "autres immobilisations corporelles": 5,
    "immobilisations corporelles en cours": 7,
    # Sous-rubriques Immobilisations financières
    "prets immobilises": 5,
    "autres creances financieres": 5,
    "titres de participation": 6,
    "autres titres immobilises": 5,
    # Écarts de conversion actif (immobilisations)
    "ecarts de conversion actif": 9,
    "diminution des creances immobilisees": 5,
    "augmentation des dettes de financement": 5,
    # Sous-rubriques Stocks
    "marchandises": 5,
    "matieres et fournitures consommables": 6,
    "produits en cours": 5,
    "produits intermediaires et produits residuels": 6,
    "produits finis": 5,
    # Sous-rubriques Créances de l'actif circulant
    "fournisseurs debiteurs avances et acomptes": 6,
    "clients et comptes rattaches": 9,
    "comptes d associes": 4,
    "autres debiteurs": 5,
    "comptes de regularis actif": 6,
    "titres et valeurs de placement": 6,
    "ecarts de conversion actif elements circulants": 6,
    # Sous-rubriques Trésorerie actif
    "cheques et valeurs a encaisser": 6,
    "banques t g et c c p": 6,
    "caisses regies d avances et accreditifs": 6,
    # Termes génériques partagés entre bilans (poids volontairement bas)
    "personnel": 3,
    "etat": 3,
}

KEYWORDS_BILAN_PASSIF: dict[str, int] = {
    # Postes structurants / totaux
    "capitaux propres": 20,
    "total des capitaux propres": 22,
    "capitaux propres assimiles": 12,
    "dettes de financement": 16,
    "provisions durables pour risques et charges": 12,
    "passif circulant": 16,
    "dettes du passif circulant": 18,
    "tresorerie passif": 22,
    # FIX (même bug que bilan_actif) : le CGNC écrit "TOTAL DU PASSIF" ou
    # "TOTAL GENERAL DU PASSIF", pas "TOTAL PASSIF" seul. On couvre les
    # variantes réelles avec le poids le plus fort dessus.
    "total passif": 10,
    "total du passif": 28,
    "total general du passif": 26,
    "total general passif": 24,
    "passif": 4,
    # Sous-rubriques Capitaux propres
    "capital social ou personnel": 10,
    "primes d emission de fusion et d apport": 6,
    "ecarts de reevaluation": 5,
    "reserve legale": 6,
    "autres reserves": 5,
    "report a nouveau": 6,
    "resultats nets en instance d affectation": 6,
    "resultat net de l exercice": 10,
    # Sous-rubriques Capitaux propres assimilés
    "subventions d investissement": 6,
    "provisions reglementees": 5,
    # Sous-rubriques Dettes de financement
    "emprunts obligataires": 6,
    "autres dettes de financement": 5,
    # Sous-rubriques Provisions durables
    "provisions pour risques": 6,
    "provisions pour charges": 6,
    "provisions pour risques et charges": 10,
    # Écarts de conversion passif
    "ecarts de conversion passif": 9,
    "augmentation des creances immobilisees": 5,
    "diminution des dettes de financement": 5,
    # Sous-rubriques Dettes du passif circulant
    "fournisseurs et comptes rattaches": 9,
    "clients crediteurs avances et acomptes": 6,
    "organismes sociaux": 6,
    "autres creanciers": 5,
    "comptes de regularisation passif": 6,
    "autres provisions pour risques et charges": 6,
    "ecarts de conversion passif elements circulants": 6,
    # Sous-rubriques Trésorerie passif
    "credits d escompte": 6,
    "credits de tresorerie": 6,
    "banques soldes crediteurs": 6,
    # Termes génériques partagés entre bilans (poids volontairement bas)
    "personnel": 3,
    "etat": 3,
}

KEYWORDS_CPC: dict[str, int] = {
    # Postes structurants / totaux
    "compte de produits et charges": 26,
    "chiffre d affaires": 20,
    "chiffres d affaires": 12,
    "produits d exploitation": 18,
    "charges d exploitation": 18,
    "resultat d exploitation": 18,
    "produits financiers": 10,
    "charges financieres": 10,
    "resultat financier": 14,
    "resultat courant": 14,
    "produits non courants": 10,
    "charges non courantes": 10,
    "resultat non courant": 12,
    "resultat avant impots": 15,
    "impots sur les resultats": 10,
    "resultat net": 8,
    # Sous-rubriques Produits d'exploitation
    "ventes de marchandises": 6,
    "ventes de biens et services produits": 6,
    "variation des stocks de produits": 6,
    "immobilisations produites par l entreprise pour elle meme": 6,
    "subventions d exploitation": 5,
    "autres produits d exploitation": 5,
    "reprises d exploitation transferts de charges": 6,
    # Sous-rubriques Charges d'exploitation
    "achats revendus de marchandises": 6,
    "achats consommes de matieres et fournitures": 6,
    "autres charges externes": 5,
    "impots et taxes": 5,
    "charges de personnel": 6,
    "autres charges d exploitation": 5,
    "dotations d exploitation": 6,
    # Sous-rubriques Produits / charges financiers
    "produits des titres de participation et autres titres immobilises": 5,
    "gains de change": 5,
    "interets et autres produits financiers": 5,
    "reprises financieres transferts de charges": 5,
    "charges d interets": 5,
    "pertes de change": 5,
    "autres charges financieres": 5,
    "dotations financieres": 5,
    # Sous-rubriques Produits / charges non courants
    "produits des cessions d immobilisations": 5,
    "subventions d equilibre": 5,
    "reprises sur subventions d investissement": 5,
    "autres produits non courants": 5,
    "reprises non courantes transferts de charges": 5,
    "valeurs nettes d amortissements des immobilisations cedees": 5,
    "subventions accordees": 4,
    "autres charges non courantes": 5,
    "dotations non courantes aux amortissements et aux provisions": 5,
}

CATEGORY_KEYWORDS: dict[str, dict[str, int]] = {
    "identification": KEYWORDS_IDENTIFICATION,
    "bilan_actif": KEYWORDS_BILAN_ACTIF,
    "bilan_passif": KEYWORDS_BILAN_PASSIF,
    "cpc": KEYWORDS_CPC,
}

# -------------------------------------------------------------------------
# FIX (bug confirmé, cas CMGP_GROUP 2024) : "Etat des Soldes de Gestion"
# (ESG) pris pour un CPC.
# -------------------------------------------------------------------------
# L'ESG est une annexe CGNC standard (calcul de la marge brute, valeur
# ajoutée, EBE, capacité d'autofinancement...) qui partage du vocabulaire
# avec le CPC ("résultat courant", "charges de personnel"...) sans être
# le CPC lui-même. Si ces rubriques, propres et UNIQUES à l'ESG,
# apparaissent, le tableau n'est pas un CPC même s'il score haut dessus.
KEYWORDS_ESG_MARKERS: list[str] = [
    "marge brute",
    "valeur ajoutee",
    "excedent brut d exploitation",
    "insuffisance brute d exploitation",
    "capacite d autofinancement",
    "autofinancement",
    "etat des soldes de gestion",
    "production de l exercice",
    "consommation de l exercice",
    "marge brute sur ventes en l etat",
]


def is_actually_esg(text_norm: str) -> bool:
    """True si le tableau est en réalité un État des Soldes de Gestion
    (ESG), pas un CPC -- au moins 2 rubriques propres à l'ESG requises
    pour éviter un faux positif sur un mot isolé."""
    hits = [m for m in KEYWORDS_ESG_MARKERS if m in text_norm]
    return len(hits) >= 2

# Expressions signalant la série comptable en cours (comptes consolidés
# vs comptes sociaux). Recherchées dans les blocs de texte qui précèdent
# un tableau, afin de contextualiser chaque tableau sans jamais recourir
# à des coordonnées / bbox.
SERIE_PATTERNS: dict[str, re.Pattern] = {
    "consolide": re.compile(r"\bcomptes?\s+consolid\w*|\bconsolid\w*\b|\betats?\s+financiers?\s+consolides?\b"),
    # FIX : les rapports reels ecrivent souvent "ETATS FINANCIERS SOCIAUX"
    # en entete de page (cas Managem confirme), pas "comptes sociaux".
    # L'ancien regex ne matchait QUE "comptes sociaux/social/individuel"
    # et manquait donc systematiquement ce cas reel tres frequent -- le
    # tableau retombait alors dans le panier "inconnue" au lieu de
    # "social", ce qui fonctionne par chance si "inconnue" gagne, mais
    # reste fragile (un document ou "consolide" aurait plus de couverture
    # choisirait alors la mauvaise serie sans le signaler).
    "social": re.compile(
        r"\bcomptes?\s+sociaux\b|\bcomptes?\s+social\b|\bcomptes?\s+individuel\w*\b"
        r"|\betats?\s+financiers?\s+sociaux\b|\bsituation\s+financiere\s+sociale\b"
    ),
}

# -------------------------------------------------------------------------
# FIX "vérifier qu'on a pris les comptes sociaux (maison mère) et non les
# comptes consolidés (incluant les filiales)".
# -------------------------------------------------------------------------
# La détection par contexte (SERIE_PATTERNS ci-dessus) dépend d'une mention
# explicite "comptes consolidés"/"comptes sociaux" trouvée en remontant les
# blocs qui précèdent le tableau -- si cette mention est absente, mal
# océrisée, ou trop loin dans le document, le tableau reste "inconnu" et
# peut être rattaché à la mauvaise série par défaut.
#
# On ajoute donc une seconde couche de détection basée sur le CONTENU même
# du tableau : certaines rubriques n'existent structurellement QUE dans des
# états consolidés (retraitements de périmètre, méthodes de consolidation,
# intérêts minoritaires, écarts d'acquisition/goodwill) et n'apparaissent
# jamais dans un bilan social individuel au format CGNC strict. Leur
# présence est un signal direct et fiable, indépendant du texte alentour.
KEYWORDS_CONSOLIDATION_MARKERS_STRONG: list[str] = [
    # Ces expressions ne peuvent structurellement apparaitre QUE dans des
    # comptes consolides -- une seule suffit, sans ambiguite connue.
    "interets minoritaires",
    "interet minoritaire",
    "ecart d acquisition",
    "ecarts d acquisition",
    "goodwill",
    "perimetre de consolidation",
    "methode de consolidation",
    "integration globale",
    "integration proportionnelle",
    "mise en equivalence",
    "societes consolidees",
    "etats financiers consolides",
    "comptes consolides",
    "resultat net part du groupe",
]

KEYWORDS_CONSOLIDATION_MARKERS_WEAK: list[str] = [
    # FIX (regression constatee en prod, ex. DELTA_HOLDING, LABEL_VIE) :
    # ces expressions peuvent, seules, apparaitre par coincidence dans un
    # document purement social (notes sur une participation, instruments
    # financiers geres au social, etc.). Un seul mot faible NE DOIT PAS
    # suffire a forcer la serie -- il en faut au moins 2 (forts ou faibles
    # combines) pour agir comme corroboration mutuelle.
    "part du groupe",
    "part des minoritaires",
    "capitaux propres attribuables aux actionnaires",
    "activites poursuivies",
    "activites abandonnees",
    "actifs non courants detenus en vue de la vente",
    "immobilisations en droit d usage",
]

# Retires : "instruments financiers derives" et "entreprises associees" /
# "entreprises integrees" -- trop generiques, vus dans de vrais documents
# sociaux marocains (banques, holdings) sans lien avec la consolidation.


def get_consolidation_markers_hit(text_norm: str) -> list[str]:
    """
    Retourne la liste des marqueurs de consolidation réellement trouvés
    dans le texte (forts ET faibles), pour traçabilité exacte dans le
    raisonnement -- indispensable pour diagnostiquer un forçage
    inattendu sans deviner. Liste vide si rien ne justifie 'consolide'.
    """
    strong_hits = [m for m in KEYWORDS_CONSOLIDATION_MARKERS_STRONG if m in text_norm]
    if strong_hits:
        return strong_hits
    weak_hits = [m for m in KEYWORDS_CONSOLIDATION_MARKERS_WEAK if m in text_norm]
    return weak_hits if len(weak_hits) >= 2 else []


def has_consolidation_markers(text_norm: str) -> bool:
    """True si le texte du tableau porte un signal suffisamment fiable
    de comptes consolidés (cf. get_consolidation_markers_hit)."""
    return bool(get_consolidation_markers_hit(text_norm))

# Score minimal pour qu'un tableau soit affecté à une catégorie plutôt
# qu'à "autre". En dessous, le signal est jugé trop faible / ambigu.
MIN_SCORE_THRESHOLD = 32

# Marge minimale entre le meilleur score et le second, pour trancher une
# ambiguïté. Si l'écart est trop faible, on préfère rester prudent.
MIN_SCORE_MARGIN = 6

# Fenêtre (en nombre de blocs) balayée en arrière pour retrouver le
# contexte de série d'un tableau.
SERIE_CONTEXT_WINDOW = 60

# Ordre de préférence par défaut entre séries lorsque plusieurs séries
# complètes sont détectées avec une couverture équivalente.
DEFAULT_SERIE_PREFERENCE = "social"


# -------------------------------------------------------------------------
# FIX "bilan_passif = tableau de dettes au lieu du bilan complet"
# -------------------------------------------------------------------------
# Un bilan (actif ou passif) marocain complet a TOUJOURS deux moitiés :
#   - Actif  : immobilisations (haut de page)  +  circulant/trésorerie (bas)
#   - Passif : capitaux propres (haut de page) +  dettes/trésorerie (bas)
# Quand MinerU détecte la page en deux blocs de tableau séparés (coupure
# visuelle, saut de page, ou simplement deux <table> HTML distincts), CHAQUE
# moitié peut à elle seule dépasser MIN_SCORE_THRESHOLD : un sous-tableau
# "Dettes de financement / Provisions / Trésorerie passif" score par
# exemple très haut sur bilan_passif sans jamais contenir "capitaux
# propres" -- c'est le cas concret remonté ("un tableau de dettes
# sélectionné au lieu du bon bilan passif").
#
# On définit donc, pour bilan_actif et bilan_passif, deux groupes de
# marqueurs correspondant aux deux moitiés obligatoires. Un tableau n'est
# considéré "complet" que s'il porte des marqueurs des DEUX groupes (ou un
# total général, qui ne peut normalement figurer que sur un tableau qui
# regroupe tout).
SECTION_MARKERS: dict[str, dict[str, list[str]]] = {
    "bilan_actif": {
        # TOTAL I : Actif immobilisé
        "immobilise": [
            "actif immobilise", "immobilisations en non valeur",
            "immobilisations incorporelles", "immobilisations corporelles",
            "immobilisations financieres",
        ],
        # TOTAL II : Actif circulant (hors trésorerie)
        "circulant": [
            "actif circulant", "creances de l actif circulant", "stocks",
            "titres et valeurs de placement",
        ],
        # TOTAL III : Trésorerie - actif
        "tresorerie": [
            "tresorerie actif", "cheques et valeurs a encaisser",
            "banques t g et c c p", "caisses regies d avances et accreditifs",
        ],
        "total_general": [
            "total actif", "total de l actif", "total general de l actif",
            "total general actif", "actif net total",
        ],
    },
    "bilan_passif": {
        # TOTAL I : Financement permanent (capitaux propres + assimilés + dettes
        # de financement + provisions durables + écarts de conversion passif)
        "financement_permanent": [
            "capitaux propres", "total des capitaux propres",
            "capitaux propres assimiles", "reserve legale",
            "report a nouveau", "resultat net de l exercice",
            "dettes de financement", "provisions durables pour risques et charges",
        ],
        # TOTAL II : Passif circulant
        "passif_circulant": [
            "passif circulant", "dettes du passif circulant",
            "fournisseurs et comptes rattaches", "organismes sociaux",
            "autres creanciers", "comptes de regularisation passif",
        ],
        # TOTAL III : Trésorerie - passif
        "tresorerie_passif": [
            "tresorerie passif", "credits d escompte", "credits de tresorerie",
            "banques soldes crediteurs",
        ],
        "total_general": [
            "total passif", "total du passif", "total general du passif",
            "total general passif",
        ],
    },
}


def section_groups_present(text_norm: str, category: str) -> set[str]:
    """Retourne les groupes de SECTION_MARKERS[category] trouvés dans text_norm."""
    groups = SECTION_MARKERS.get(category, {})
    return {
        group_name for group_name, phrases in groups.items()
        if any(p in text_norm for p in phrases)
    }


def is_complete_bilan_table(text_norm: str, category: str) -> bool:
    """
    Un tableau bilan_actif/bilan_passif est jugé COMPLET s'il porte un
    total général explicite, OU s'il porte des marqueurs des deux moitiés
    obligatoires (haut ET bas de page). Un tableau qui ne porte QU'une
    seule moitié (typiquement : seulement la partie "dettes") est partiel.
    """
    if category not in SECTION_MARKERS:
        return True  # catégorie non concernée (identification, cpc)

    present = section_groups_present(text_norm, category)
    if "total_general" in present:
        return True
    non_total_groups = {g for g in SECTION_MARKERS[category] if g != "total_general"}
    return non_total_groups.issubset(present)


# =========================================================================
# 3. STRUCTURES DE DONNÉES
# =========================================================================

@dataclass
class TableCandidate:
    """Représente un tableau détecté par MinerU, enrichi de l'analyse."""

    table_id: int
    page: Optional[int]
    image_path: Optional[Path]           # chemin absolu résolu sur disque
    image_rel: Optional[str]             # chemin tel que fourni par MinerU
    caption: str
    footnote: str
    html: str
    text_norm: str                       # texte normalisé (sans accents, minuscule)
    block_index: int                     # position dans content_list.json (ordre de lecture)

    serie: str = "inconnue"              # "consolide" | "social" | "inconnue" | "unique"

    scores: dict[str, int] = field(default_factory=dict)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)

    predicted_type: str = "autre"
    score: int = 0
    confidence: float = 0.0
    reasoning: list[str] = field(default_factory=list)

    selected: bool = False

    # Rempli par repair_partial_bilan_tables() quand ce tableau a été
    # complété par un ou plusieurs tableaux voisins (ex: "Actif immobilisé"
    # + "Actif circulant" + "Trésorerie actif" fusionnés en un seul
    # bilan_actif complet -- un bilan CGNC a 3 sections, pas 2).
    merge_partner: Optional["TableCandidate"] = None
    merge_partners: list["TableCandidate"] = field(default_factory=list)


# =========================================================================
# 4. ÉTAPE A - EXÉCUTION DE MINERU
# =========================================================================

# Valeurs acceptées par le flag -l/--lang du CLI MinerU. Ce flag ne sert
# qu'à activer un modèle OCR spécialisé pour des écritures NON LATINES
# (chinois, coréen, tamoul, arabe, cyrillique, devanagari...). Les langues
# à écriture latine (français, anglais, espagnol...) sont couvertes par le
# modèle OCR par défaut et NE DOIVENT PAS être passées via -l, sous peine
# d'une erreur "Language ... not supported" de MinerU.
MINERU_SUPPORTED_LANG_FLAGS = {
    "ch", "ch_server", "korean", "ta", "te", "ka", "th", "el",
    "arabic", "east_slavic", "cyrillic", "devanagari",
}


def run_mineru(pdf_path: Path, output_dir: Path, lang: Optional[str], backend: str) -> None:
    """
    Lance MinerU en ligne de commande sur le PDF fourni.

    On ne dépend d'aucune API interne de MinerU : on invoque le binaire
    CLI officiel (`mineru`), ce qui rend le script robuste aux évolutions
    internes de la librairie et facile à auditer / déboguer manuellement.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "mineru",
        "-p", str(pdf_path),
        "-o", str(output_dir),
        "-b", backend,
    ]

    if lang:
        if lang in MINERU_SUPPORTED_LANG_FLAGS:
            cmd += ["-l", lang]
        else:
            # Cas des rapports marocains en français : on n'ajoute PAS -l
            # (l'OCR latin par défaut de MinerU gère le français sans ce
            # flag). On avertit simplement au lieu de planter, pour rester
            # robuste face aux futures évolutions de la liste MinerU.
            log.warning(
                "Langue '%s' non reconnue par le flag -l de MinerU (valeurs "
                "acceptées : %s). Le flag -l est omis ; l'OCR latin par "
                "défaut sera utilisé, ce qui convient au français.",
                lang, sorted(MINERU_SUPPORTED_LANG_FLAGS),
            )

    log.info("Lancement de MinerU : %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            log.debug("MinerU stdout:\n%s", result.stdout)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Le binaire 'mineru' est introuvable dans le PATH. "
            "Installez MinerU (pip install -U 'mineru[all]') ou utilisez "
            "--skip-mineru avec --mineru-output si la sortie existe déjà."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"MinerU a échoué (code {exc.returncode}).\n"
            f"--- stdout ---\n{exc.stdout}\n--- stderr ---\n{exc.stderr}"
        ) from exc

    log.info("MinerU terminé avec succès.")


def find_content_list_json(output_dir: Path, pdf_stem: str) -> Path:
    """
    Localise le fichier <stem>_content_list.json produit par MinerU.

    MinerU range ses sorties dans une arborescence du type :
        output_dir/<stem>/<method>/<stem>_content_list.json
    où <method> dépend du backend (auto, ocr, txt, vlm...). Plutôt que de
    supposer une structure figée, on parcourt récursivement le dossier de
    sortie, ce qui rend le script tolérant aux changements de version de
    MinerU.
    """
    candidates = sorted(output_dir.rglob(f"{pdf_stem}_content_list.json"))
    if not candidates:
        # Repli : n'importe quel *_content_list.json (utile si le nom du
        # PDF a été légèrement assaini par MinerU : espaces, accents...).
        candidates = sorted(output_dir.rglob("*_content_list.json"))

    if not candidates:
        raise FileNotFoundError(
            f"Aucun fichier '*_content_list.json' trouvé sous {output_dir}. "
            "Vérifiez que MinerU a bien produit une sortie complète."
        )

    if len(candidates) > 1:
        log.warning(
            "Plusieurs fichiers content_list.json trouvés, utilisation du "
            "premier : %s", candidates[0]
        )

    return candidates[0]


# =========================================================================
# 5. ÉTAPE B - LECTURE ET NORMALISATION DES BLOCS MINERU
# =========================================================================

def strip_html_to_text(html: str) -> str:
    """Aplati un extrait HTML de tableau en texte brut exploitable."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_text(text: str) -> str:
    """
    Normalise un texte pour la recherche de mots-clés :
    minuscules + suppression des accents (les rapports marocains mélangent
    orthographes accentuées et non accentuées selon la qualité de l'OCR).
    """
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # On retire toute ponctuation (apostrophes, virgules, tirets...) car les
    # phrases-clés sont écrites sans ponctuation ("chiffre d affaires").
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def as_joined_text(value) -> str:
    """
    Les champs 'table_caption' / 'table_footnote' de MinerU peuvent être
    une simple chaîne ou une liste de chaînes selon la version. On
    normalise ici pour toujours travailler avec du texte.
    """
    if not value:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    return str(value)


def load_content_blocks(content_list_path: Path) -> list[dict]:
    """Charge le contenu brut de content_list.json."""
    with open(content_list_path, "r", encoding="utf-8") as f:
        blocks = json.load(f)
    if not isinstance(blocks, list):
        raise ValueError(f"{content_list_path} ne contient pas une liste de blocs.")
    return blocks


def resolve_image_path(base_dir: Path, img_rel: str) -> Optional[Path]:
    """Résout le chemin d'image relatif fourni par MinerU."""
    if not img_rel:
        return None
    candidate = (base_dir / img_rel).resolve()
    return candidate if candidate.exists() else None


def build_table_candidates(blocks: list[dict], base_dir: Path) -> list[TableCandidate]:
    """
    Parcourt les blocs MinerU dans l'ordre de lecture et construit un
    TableCandidate pour chaque bloc de type "table".
    """
    candidates: list[TableCandidate] = []
    table_counter = 0

    for idx, block in enumerate(blocks):
        if block.get("type") != "table":
            continue

        table_counter += 1
        html = block.get("table_body", "") or ""
        caption = as_joined_text(block.get("table_caption"))
        footnote = as_joined_text(block.get("table_footnote"))
        img_rel = block.get("img_path", "") or ""

        raw_text = " ".join([caption, footnote, strip_html_to_text(html)])
        text_norm = normalize_text(raw_text)

        candidate = TableCandidate(
            table_id=table_counter,
            page=block.get("page_idx"),
            image_path=resolve_image_path(base_dir, img_rel),
            image_rel=img_rel or None,
            caption=caption,
            footnote=footnote,
            html=html,
            text_norm=text_norm,
            block_index=idx,
        )
        candidates.append(candidate)

    log.info("Tableaux détectés par MinerU : %d", len(candidates))
    return candidates


# =========================================================================
# 6. ÉTAPE C - DÉTECTION DE LA SÉRIE (CONSOLIDÉ / SOCIAL)
# =========================================================================

def detect_serie_context(blocks: list[dict], candidates: list[TableCandidate]) -> None:
    """
    Pour chaque tableau, remonte le flux de blocs (ordre de lecture, tel
    que fourni par MinerU) afin de trouver la mention la plus proche de
    "comptes consolidés" ou "comptes sociaux". Cela permet de savoir à
    quelle série appartient chaque tableau sans aucune coordonnée bbox :
    on exploite uniquement l'ordre séquentiel déjà garanti par MinerU.
    """
    # Texte normalisé de chaque bloc (une seule fois, pour la performance).
    block_texts: list[str] = []
    for block in blocks:
        raw = ""
        if block.get("type") == "text":
            raw = block.get("text", "") or ""
        elif block.get("type") == "table":
            raw = " ".join([
                as_joined_text(block.get("table_caption")),
                as_joined_text(block.get("table_footnote")),
            ])
        block_texts.append(normalize_text(raw))

    any_serie_marker_in_doc = any(
        SERIE_PATTERNS["consolide"].search(t) or SERIE_PATTERNS["social"].search(t)
        for t in block_texts
    )

    for cand in candidates:
        markers_hit = get_consolidation_markers_hit(cand.text_norm)
        table_has_consolidation_markers = bool(markers_hit)

        # FIX (cas ZELLIDJA_S.A 2025, confirmé par capture d'écran) :
        # le libellé "COMPTES SOCIAUX" / "COMPTES CONSOLIDÉS" peut être
        # une bannière imprimée DANS le tableau lui-même (au-dessus des
        # colonnes ACTIF/PASSIF), pas dans un paragraphe de texte séparé.
        # Le scan de contexte (block_texts, ci-dessous) ne regarde QUE les
        # blocs "text" et les caption/footnote des tableaux -- jamais le
        # HTML complet d'un tableau -- donc il rate ce cas. On vérifie
        # donc D'ABORD le texte propre du tableau (qui inclut son HTML) :
        # si le libellé y est trouvé, c'est le signal le plus direct
        # possible, plus fiable que n'importe quel contexte alentour.
        if SERIE_PATTERNS["consolide"].search(cand.text_norm):
            cand.serie = "consolide"
            cand.reasoning.append(
                "Série 'consolide' trouvée directement dans le texte du tableau "
                "lui-même (ex: bannière \"COMPTES CONSOLIDÉS\" imprimée dans le tableau)."
            )
            continue
        if SERIE_PATTERNS["social"].search(cand.text_norm):
            cand.serie = "social"
            cand.reasoning.append(
                "Série 'social' trouvée directement dans le texte du tableau "
                "lui-même (ex: bannière \"COMPTES SOCIAUX\" imprimée dans le tableau)."
            )
            continue

        if not any_serie_marker_in_doc:
            # FIX : même si aucune mention "comptes consolidés/sociaux"
            # n'existe nulle part dans le flux de blocs (donc le contexte
            # ne peut par définition rien nous dire), le CONTENU du tableau
            # peut trancher : des rubriques comme "intérêts minoritaires"
            # ou "écart d'acquisition" ne peuvent apparaître que dans des
            # comptes consolidés.
            if table_has_consolidation_markers:
                cand.serie = "consolide"
                cand.reasoning.append(
                    f"Série 'consolide' détectée via le contenu du tableau lui-même "
                    f"(mot(s)/expression(s) trouvé(s) : {', '.join(markers_hit)}), en "
                    f"l'absence de tout marqueur textuel 'comptes consolidés/sociaux' "
                    f"ailleurs dans le document."
                )
            else:
                cand.serie = "unique"
            continue

        found_serie = None
        start = cand.block_index
        lower_bound = max(0, start - SERIE_CONTEXT_WINDOW)

        for i in range(start, lower_bound - 1, -1):
            t = block_texts[i]
            if not t:
                continue
            if SERIE_PATTERNS["consolide"].search(t):
                found_serie = "consolide"
                break
            if SERIE_PATTERNS["social"].search(t):
                found_serie = "social"
                break

        if table_has_consolidation_markers and found_serie != "consolide":
            # FIX du cas "on a pris social au lieu de consolidé (ou
            # l'inverse)" : le contenu du tableau prime sur un contexte
            # absent, trop lointain, ou mal océrisé. On force 'consolide'
            # et on trace explicitement le conflit pour audit si le
            # contexte affirmait le contraire -- avec le(s) mot(s) EXACT(S)
            # trouvé(s), pas un exemple générique, pour pouvoir diagnostiquer
            # un faux positif sans deviner.
            if found_serie == "social":
                cand.reasoning.append(
                    f"ATTENTION : contexte textuel indiquait 'social' mais le tableau "
                    f"contient : {', '.join(markers_hit)} -- série forcée à 'consolide', "
                    f"à vérifier manuellement."
                )
            else:
                cand.reasoning.append(
                    f"Série 'consolide' confirmée/forcée par le contenu du tableau "
                    f"(mot(s)/expression(s) trouvé(s) : {', '.join(markers_hit)})."
                )
            found_serie = "consolide"

        cand.serie = found_serie or "inconnue"


# =========================================================================
# 7. ÉTAPE D - SCORING SÉMANTIQUE DES TABLEAUX
# =========================================================================

def score_candidate_against_category(text_norm: str, keywords: dict[str, int]) -> tuple[int, list[str]]:
    """Calcule le score brut d'un tableau pour une catégorie donnée."""
    raw_score = 0
    matched: list[str] = []
    for phrase, weight in keywords.items():
        if phrase in text_norm:
            raw_score += weight
            matched.append(phrase)
    return min(raw_score, 100), matched


def has_tabular_structure(html: str, min_rows: int = 3) -> bool:
    """
    Vérifie grossièrement que le HTML ressemble bien à un tableau
    structuré (plusieurs lignes). Sert de bonus de vraisemblance, pas de
    critère bloquant : certains tableaux financiers mal océrisés restent
    valides malgré une structure HTML pauvre.
    """
    if not html:
        return False
    return len(re.findall(r"<tr\b", html, flags=re.IGNORECASE)) >= min_rows


def score_all_candidates(candidates: list[TableCandidate]) -> None:
    """Calcule, pour chaque tableau, le score de chaque catégorie et
    détermine le type prédit avec seuil de confiance et marge anti-ambiguïté.
    """
    for cand in candidates:
        for category, keywords in CATEGORY_KEYWORDS.items():
            score, matched = score_candidate_against_category(cand.text_norm, keywords)
            cand.scores[category] = score
            cand.matched_keywords[category] = matched

        # Classement des catégories par score décroissant.
        ranked = sorted(cand.scores.items(), key=lambda kv: kv[1], reverse=True)
        best_category, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0

        # FIX (cas CMGP_GROUP 2024) : si le meilleur candidat est "cpc"
        # mais que le tableau est en réalité un État des Soldes de
        # Gestion (ESG), on l'exclut de la course CPC en remettant son
        # score cpc à 0 et on reclasse -- sinon l'ESG, qui partage du
        # vocabulaire avec le CPC, gagne parfois à tort face au vrai CPC.
        esg_detected = best_category == "cpc" and is_actually_esg(cand.text_norm)
        if esg_detected:
            cand.scores["cpc"] = 0
            ranked = sorted(cand.scores.items(), key=lambda kv: kv[1], reverse=True)
            best_category, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else 0

        # On complète le raisonnement déjà amorcé par detect_serie_context
        # (notes sur la série sociale/consolidée) au lieu de l'écraser.
        reasoning: list[str] = list(cand.reasoning)
        if esg_detected:
            reasoning.append(
                "ATTENTION : ce tableau ressemble à un État des Soldes de Gestion (ESG), "
                "pas au CPC lui-même (rubriques comme valeur ajoutée / EBE / capacité "
                "d'autofinancement détectées) -- exclu de la sélection CPC."
            )
        structure_ok = has_tabular_structure(cand.html)
        if structure_ok:
            reasoning.append("Structure HTML compatible (tableau à plusieurs lignes)")

        if best_score >= MIN_SCORE_THRESHOLD and (best_score - second_score) >= MIN_SCORE_MARGIN:
            cand.predicted_type = best_category
            cand.score = best_score
            matched_list = cand.matched_keywords[best_category]
            if matched_list:
                reasoning.append(
                    "Rubriques comptables reconnues : " + ", ".join(matched_list[:6])
                )
        else:
            cand.predicted_type = "autre"
            cand.score = best_score
            if best_score:
                reasoning.append(
                    f"Signal insuffisant ou ambigu (meilleur='{best_category}':{best_score}, "
                    f"second={second_score}) -> classé 'autre'"
                )
            else:
                reasoning.append("Aucune rubrique comptable reconnue")

        cand.confidence = round(cand.score / 100, 2)
        cand.reasoning = reasoning


def find_missing_side_partner(
    cand: TableCandidate, all_candidates: list[TableCandidate], category: str, window: int = 6
) -> Optional[TableCandidate]:
    """
    Cherche, parmi les tableaux voisins (proximité en ordre de lecture,
    même série comptable), celui qui porte UNE des sections manquantes à
    `cand` pour `category` (ex: cand a seulement "Actif immobilisé", on
    cherche un voisin qui a "Actif circulant" OU "Trésorerie actif" --
    un bilan CGNC a 3 sections obligatoires, pas 2, donc plusieurs appels
    successifs peuvent être nécessaires pour tout reconstituer).
    """
    groups = SECTION_MARKERS[category]
    non_total_groups = {g for g in groups if g != "total_general"}
    present = section_groups_present(cand.text_norm, category)
    missing_groups = non_total_groups - present
    if not missing_groups:
        return None

    missing_phrases: list[str] = []
    for g in missing_groups:
        missing_phrases.extend(groups[g])

    best_partner: Optional[TableCandidate] = None
    best_distance: Optional[int] = None
    for other in all_candidates:
        if other.table_id == cand.table_id:
            continue
        if cand.serie not in ("unique", "inconnue") and other.serie not in ("unique", "inconnue") \
                and other.serie != cand.serie:
            continue
        # On ne "consomme" que des tableaux qui ne sont pas déjà une autre
        # catégorie clairement identifiée : soit "autre", soit déjà la
        # même catégorie (cas classique du bilan coupé en deux blocs).
        if other.predicted_type not in (category, "autre"):
            continue
        # FIX (regression constatee en prod : un "bilan_actif" complete
        # a tort par un petit bloc de notes/sommaire qui mentionne juste
        # "immobilisations incorporelles" sans etre un vrai tableau
        # financier). On exige une vraie structure de tableau HTML
        # (plusieurs lignes <tr>), pas seulement un mot-cle qui matche.
        if not has_tabular_structure(other.html):
            continue
        distance = abs(other.block_index - cand.block_index)
        if distance > window:
            continue
        if any(p in other.text_norm for p in missing_phrases):
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_partner = other
    return best_partner


def repair_partial_bilan_tables(candidates: list[TableCandidate]) -> None:
    """
    FIX du cas concret remonté : "un bilan_passif (tableau des dettes) est
    sélectionné au lieu du bon". Quand MinerU détecte le bilan actif ou
    passif en deux blocs séparés (haut de page "capitaux/immobilisations"
    et bas de page "dettes/circulant+trésorerie"), chaque moitié peut
    individuellement dépasser le seuil de score et être typée comme la
    bonne catégorie -- mais celle qui porte le plus de sous-rubriques
    détaillées (souvent la moitié "dettes", très détaillée) gagne alors
    par score brut, sans être le bilan complet.

    Cette fonction détecte les tableaux partiels (is_complete_bilan_table
    == False) et va chercher, un par un, les tableaux voisins qui portent
    chaque section manquante -- un bilan CGNC ayant 3 sections
    obligatoires (ex: Actif immobilisé / Actif circulant / Trésorerie),
    il peut falloir fusionner jusqu'à 2 tableaux voisins supplémentaires,
    pas un seul. Le voisin absorbé est requalifié en "fusionne" pour ne
    plus concurrencer séparément. Si une section reste introuvable après
    toutes les tentatives, le tableau est laissé tel quel mais sa
    confiance est réduite et sa justification signale le risque, afin que
    l'audit (audit_selected_tables.py) le remonte pour relecture manuelle.
    """
    MAX_MERGES_PER_TABLE = 3  # un bilan CGNC a au plus 3 sections obligatoires

    for category in ("bilan_actif", "bilan_passif"):
        cat_candidates = [c for c in candidates if c.predicted_type == category]
        consumed_as_partner: set[int] = set()

        for cand in sorted(cat_candidates, key=lambda c: -c.score):
            if cand.merge_partner is not None or cand.predicted_type == "fusionne":
                continue
            if cand.table_id in consumed_as_partner:
                # Déjà absorbé comme partenaire d'un autre tableau plus
                # haut dans cette boucle : ne pas le retraiter séparément.
                continue
            if is_complete_bilan_table(cand.text_norm, category):
                continue

            merged_ids: list[int] = []
            for _ in range(MAX_MERGES_PER_TABLE):
                if is_complete_bilan_table(cand.text_norm, category):
                    break

                partner = find_missing_side_partner(cand, candidates, category)
                if partner is not None and partner.table_id in consumed_as_partner:
                    partner = None
                if partner is None:
                    break

                merged_text = cand.text_norm + " " + partner.text_norm
                merged_html = (cand.html or "") + (partner.html or "")

                for cat2, keywords2 in CATEGORY_KEYWORDS.items():
                    score2, matched2 = score_candidate_against_category(merged_text, keywords2)
                    cand.scores[cat2] = score2
                    cand.matched_keywords[cat2] = matched2

                cand.text_norm = merged_text
                cand.html = merged_html
                cand.score = cand.scores[category]
                cand.confidence = round(cand.score / 100, 2)

                if cand.merge_partner is None:
                    cand.merge_partner = partner  # rétro-compat : 1er partenaire
                cand.merge_partners.append(partner)
                consumed_as_partner.add(partner.table_id)
                merged_ids.append(partner.table_id)

                if partner.predicted_type != category:
                    partner.predicted_type = "fusionne"
                partner.reasoning.append(
                    f"Fusionné avec le tableau #{cand.table_id} (reconstitution d'un {category} complet)."
                )

            if merged_ids:
                cand.reasoning.append(
                    f"Assemblage automatique : tableau #{cand.table_id} complété avec le(s) "
                    f"tableau(x) voisin(s) #{', #'.join(str(i) for i in merged_ids)} pour "
                    f"reconstituer un {category} complet (3 sections CGNC)."
                )

            if not is_complete_bilan_table(cand.text_norm, category):
                missing = sorted(
                    set(SECTION_MARKERS[category]) - {"total_general"}
                    - section_groups_present(cand.text_norm, category)
                )
                cand.reasoning.append(
                    "ATTENTION : tableau probablement PARTIEL (section(s) manquante(s) : "
                    f"{', '.join(missing)}) -- aucun tableau voisin complémentaire trouvé pour "
                    "la/les compléter -- vérification manuelle recommandée."
                )
                cand.confidence = round(cand.confidence * 0.6, 2)


def add_neighbor_coherence_reasoning(candidates: list[TableCandidate]) -> None:
    """
    Ajoute une justification de cohérence lorsque deux tableaux voisins
    (dans l'ordre de lecture, même série) forment une paire logique
    attendue (ex: Bilan Actif suivi de Bilan Passif, ou Bilan Passif suivi
    du CPC). Ceci renforce la traçabilité du JSON de sortie, conformément
    à l'exemple demandé ("Cohérence avec Bilan Passif page suivante").
    """
    expected_next = {
        "identification": {"bilan_actif"},
        "bilan_actif": {"bilan_passif"},
        "bilan_passif": {"cpc"},
    }

    typed = [c for c in candidates if c.predicted_type != "autre"]
    typed.sort(key=lambda c: c.block_index)

    for i, cand in enumerate(typed):
        expected = expected_next.get(cand.predicted_type)
        if not expected:
            continue
        for nxt in typed[i + 1: i + 4]:  # on regarde les tableaux typés suivants proches
            if nxt.serie != cand.serie and cand.serie != "unique":
                continue
            if nxt.predicted_type in expected:
                page_info = (
                    f"page {nxt.page}" if nxt.page is not None else "page suivante"
                )
                cand.reasoning.append(
                    f"Cohérence avec {nxt.predicted_type} ({page_info})"
                )
                break


# =========================================================================
# 8. ÉTAPE E - SÉLECTION D'UNE SÉRIE UNIQUE ET COHÉRENTE
# =========================================================================

REQUIRED_CATEGORIES = ["identification", "bilan_actif", "bilan_passif", "cpc"]


def select_coherent_serie(
    candidates: list[TableCandidate], serie_preference: str
) -> tuple[str, dict[str, Optional[TableCandidate]]]:
    """
    Détermine la série comptable (consolidé / social / unique / inconnue)
    à retenir pour l'ensemble du document, puis sélectionne, pour cette
    série, le meilleur tableau de chaque catégorie.

    Stratégie :
      1. Regrouper les tableaux typés par série.
      2. Pour chaque série, calculer une couverture (nb de catégories
         représentées) et un score cumulé (somme des meilleurs scores).
      3. Choisir la série avec la meilleure couverture, puis le meilleur
         score cumulé, puis en dernier recours la préférence utilisateur.
      4. Dans la série retenue, choisir le meilleur candidat par catégorie.
    """
    by_serie: dict[str, list[TableCandidate]] = {}
    for cand in candidates:
        if cand.predicted_type == "autre":
            continue
        by_serie.setdefault(cand.serie, []).append(cand)

    if not by_serie:
        log.warning("Aucun tableau financier reconnu dans le document.")
        return "inconnue", {cat: None for cat in REQUIRED_CATEGORIES}

    def best_per_category(cands: list[TableCandidate]) -> dict[str, Optional[TableCandidate]]:
        result: dict[str, Optional[TableCandidate]] = {cat: None for cat in REQUIRED_CATEGORIES}
        for cat in REQUIRED_CATEGORIES:
            same_cat = [c for c in cands if c.predicted_type == cat]
            if same_cat:
                result[cat] = max(same_cat, key=lambda c: c.score)
        return result

    serie_summary: dict[str, dict] = {}
    for serie, cands in by_serie.items():
        best = best_per_category(cands)
        coverage = sum(1 for v in best.values() if v is not None)
        total_score = sum(v.score for v in best.values() if v is not None)
        serie_summary[serie] = {
            "best": best,
            "coverage": coverage,
            "total_score": total_score,
        }

    def sort_key(item):
        serie, summary = item
        preference_bonus = 1 if serie == serie_preference else 0
        return (summary["coverage"], summary["total_score"], preference_bonus)

    chosen_serie, chosen_summary = max(serie_summary.items(), key=sort_key)

    log.info(
        "Série retenue : '%s' (couverture=%d/4, score cumulé=%d) parmi séries candidates : %s",
        chosen_serie,
        chosen_summary["coverage"],
        chosen_summary["total_score"],
        {s: v["coverage"] for s, v in serie_summary.items()},
    )

    return chosen_serie, chosen_summary["best"]


def mark_selection(
    candidates: list[TableCandidate],
    selection: dict[str, Optional[TableCandidate]],
    chosen_serie: str,
) -> None:
    """Marque les tableaux gagnants comme 'selected' et enrichit leur raisonnement."""
    winners = {c.table_id for c in selection.values() if c is not None}
    for cand in candidates:
        if cand.table_id in winners:
            cand.selected = True
            cand.reasoning.append(
                f"Sélectionné comme meilleur '{cand.predicted_type}' de la série '{chosen_serie}'"
            )


# =========================================================================
# 9. ÉTAPE F - GÉNÉRATION DES SORTIES (JSON + IMAGES RENOMMÉES)
# =========================================================================

def save_image_as_png(src: Path, dst_png: Path) -> bool:
    """Copie une image source vers dst_png, en convertissant en PNG si Pillow
    est disponible. Retourne True si l'opération a réussi."""
    try:
        dst_png.parent.mkdir(parents=True, exist_ok=True)
        if _PIL_AVAILABLE:
            with Image.open(src) as im:
                im.convert("RGB").save(dst_png, format="PNG")
        else:
            # Repli sans Pillow : copie brute en conservant l'extension
            # d'origine si elle diffère de .png (mieux vaut une image
            # exploitable qu'un renommage trompeur).
            if src.suffix.lower() == ".png":
                shutil.copyfile(src, dst_png)
            else:
                dst_fallback = dst_png.with_suffix(src.suffix)
                shutil.copyfile(src, dst_fallback)
                log.warning(
                    "Pillow indisponible : image copiée sans conversion PNG -> %s",
                    dst_fallback,
                )
        return True
    except Exception as exc:  # noqa: BLE001 - on veut journaliser puis continuer
        log.error("Échec de copie de l'image %s -> %s : %s", src, dst_png, exc)
        return False


def save_merged_images_as_png(sources: list[Path], dst_png: Path) -> bool:
    """
    Empile verticalement N images de tableaux (ex: Actif immobilisé +
    Actif circulant + Trésorerie actif) en un seul PNG, pour livrer une
    image complète quand un bilan a été reconstitué à partir de 2 ou 3
    blocs MinerU voisins (cf. repair_partial_bilan_tables -- un bilan
    CGNC a 3 sections obligatoires, pas 2). `sources` doit déjà être
    trié dans l'ordre de lecture (haut de page en premier).
    Sans Pillow, on ne peut pas empiler proprement : on retombe sur une
    simple copie de la première image (la plus haute dans la page), avec
    un avertissement.
    """
    try:
        dst_png.parent.mkdir(parents=True, exist_ok=True)
        if not _PIL_AVAILABLE:
            log.warning(
                "Pillow indisponible : impossible d'empiler %d images (%s), copie de la 1ere seule.",
                len(sources), sources,
            )
            return save_image_as_png(sources[0], dst_png)

        opened = [Image.open(p).convert("RGB") for p in sources]
        width = max(im.width for im in opened)
        resized = [
            im if im.width == width else im.resize((width, int(im.height * width / im.width)))
            for im in opened
        ]
        total_height = sum(im.height for im in resized)
        combined = Image.new("RGB", (width, total_height), "white")
        y = 0
        for im in resized:
            combined.paste(im, (0, y))
            y += im.height
        combined.save(dst_png, format="PNG")
        for im in opened:
            im.close()
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Échec de fusion de %d images -> %s : %s", len(sources), dst_png, exc)
        return False


def export_selected_images(
    selection: dict[str, Optional[TableCandidate]], selected_dir: Path
) -> None:
    """Crée selected_tables/ et copie les images gagnantes avec les noms attendus."""
    selected_dir.mkdir(parents=True, exist_ok=True)

    for category, cand in selection.items():
        if cand is None:
            log.warning("Aucun tableau retenu pour la catégorie '%s'.", category)
            continue
        has_any_image = cand.image_path is not None or any(
            p.image_path is not None for p in cand.merge_partners
        )
        if not has_any_image:
            log.warning(
                "Tableau #%d retenu pour '%s' mais aucune image (ni la sienne ni celle "
                "d'un tableau fusionné) introuvable sur disque.",
                cand.table_id, category,
            )
            continue

        dst = selected_dir / f"{category}.png"

        if cand.merge_partners:
            pieces = [cand] + cand.merge_partners
            pieces_with_image = [p for p in pieces if p.image_path is not None]
            pieces_with_image.sort(key=lambda p: p.block_index)
            sources = [p.image_path for p in pieces_with_image]
            if len(sources) >= 2:
                ok = save_merged_images_as_png(sources, dst)
                if ok:
                    ids = "+".join(f"#{p.table_id}" for p in pieces_with_image)
                    log.info(
                        "Image fusionnée exportée : %s (tableaux %s, score=%d)",
                        dst, ids, cand.score,
                    )
                continue
            # une seule image récupérable malgré la fusion textuelle : repli simple copie
            if sources:
                ok = save_image_as_png(sources[0], dst)
                if ok:
                    log.info("Image exportée : %s (tableau #%d, score=%d)", dst, cand.table_id, cand.score)
                continue

        ok = save_image_as_png(cand.image_path, dst)
        if ok:
            log.info("Image exportée : %s (tableau #%d, score=%d)", dst, cand.table_id, cand.score)


def build_output_json(
    document_name: str,
    mineru_output_dir: Path,
    candidates: list[TableCandidate],
    chosen_serie: str,
    selection: dict[str, Optional[TableCandidate]],
) -> dict:
    """Construit la structure JSON finale conforme au besoin exprimé."""
    detected_series = sorted({c.serie for c in candidates})

    tables_json = []
    for cand in sorted(candidates, key=lambda c: c.table_id):
        tables_json.append({
            "table_id": cand.table_id,
            "page": cand.page,
            "image": cand.image_rel,
            "type": cand.predicted_type,
            "score": cand.score,
            "confidence": cand.confidence,
            "serie": cand.serie,
            "selected": cand.selected,
            "matched_keywords": cand.matched_keywords.get(cand.predicted_type, []),
            "all_scores": cand.scores,
            "reasoning": cand.reasoning,
        })

    output = {
        "document": document_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mineru_output_dir": str(mineru_output_dir),
        "detected_series": detected_series,
        "selected_serie": chosen_serie,
        "selection": {
            category: (cand.table_id if cand is not None else None)
            for category, cand in selection.items()
        },
        "tables": tables_json,
    }
    return output


# =========================================================================
# 10. ORCHESTRATION PRINCIPALE
# =========================================================================

def process_pdf(
    pdf_path: Path,
    output_dir: Path,
    lang: str,
    backend: str,
    skip_mineru: bool,
    mineru_output_override: Optional[Path],
    serie_preference: str,
) -> Path:
    """Exécute le pipeline complet du Script 1 pour un PDF donné."""

    pdf_stem = pdf_path.stem
    mineru_output_dir = mineru_output_override or (output_dir / "mineru_raw")

    # --- A. Exécution de MinerU -----------------------------------------
    if skip_mineru:
        log.info("Étape MinerU ignorée (--skip-mineru), utilisation de : %s", mineru_output_dir)
        if not mineru_output_dir.exists():
            raise FileNotFoundError(f"Dossier de sortie MinerU introuvable : {mineru_output_dir}")
    else:
        run_mineru(pdf_path, mineru_output_dir, lang=lang, backend=backend)

    # --- B. Localisation et lecture de content_list.json ------------------
    content_list_path = find_content_list_json(mineru_output_dir, pdf_stem)
    log.info("content_list.json localisé : %s", content_list_path)
    base_dir = content_list_path.parent

    blocks = load_content_blocks(content_list_path)
    candidates = build_table_candidates(blocks, base_dir)

    if not candidates:
        raise RuntimeError(
            "MinerU n'a détecté aucun tableau dans ce PDF. "
            "Vérifiez la qualité du PDF ou le backend utilisé (-b)."
        )

    # --- C. Contexte de série (consolidé / social) -------------------------
    detect_serie_context(blocks, candidates)

    # --- D. Scoring sémantique ----------------------------------------------
    score_all_candidates(candidates)
    repair_partial_bilan_tables(candidates)
    add_neighbor_coherence_reasoning(candidates)

    # --- E. Sélection d'une série cohérente unique --------------------------
    chosen_serie, selection = select_coherent_serie(candidates, serie_preference)
    mark_selection(candidates, selection, chosen_serie)

    # --- F. Génération des sorties -------------------------------------------
    output_json = build_output_json(pdf_stem, mineru_output_dir, candidates, chosen_serie, selection)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{pdf_stem}_tables_analysis.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)
    log.info("JSON d'analyse écrit : %s", json_path)

    selected_dir = output_dir / "selected_tables"
    export_selected_images(selection, selected_dir)

    # --- Résumé console -------------------------------------------------------
    log.info("=" * 70)
    log.info("RÉSUMÉ - %s", pdf_stem)
    log.info("Série retenue : %s", chosen_serie)
    for category, cand in selection.items():
        if cand is not None:
            log.info(
                "  %-15s -> tableau #%-3d | page %-4s | score %-3d | confiance %.2f",
                category, cand.table_id, cand.page, cand.score, cand.confidence,
            )
        else:
            log.warning("  %-15s -> NON TROUVÉ", category)
    log.info("=" * 70)

    return json_path


# =========================================================================
# 11. INTERFACE LIGNE DE COMMANDE
# =========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Script 1 du pipeline Document AI TPME : lance MinerU sur un PDF, "
            "puis sélectionne intelligemment les tableaux Identification, "
            "Bilan Actif, Bilan Passif et CPC parmi les tableaux détectés."
        )
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Chemin du PDF à traiter.")
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Dossier de sortie du Script 1 (par défaut : ./output/<nom_pdf>/).",
    )
    parser.add_argument(
        "--mineru-output", dest="mineru_output_override", type=Path, default=None,
        help="Dossier de sortie MinerU à utiliser/produire (par défaut : <output-dir>/mineru_raw).",
    )
    parser.add_argument(
        "--lang", default=None,
        help=(
            "Langue OCR à forcer via -l MinerU, UNIQUEMENT pour une écriture "
            "non latine (ch, ch_server, korean, ta, te, ka, th, el, arabic, "
            "east_slavic, cyrillic, devanagari). Ne pas renseigner pour le "
            "français : l'OCR latin par défaut de MinerU s'applique déjà."
        ),
    )
    parser.add_argument(
        "--backend", default="pipeline",
        choices=["pipeline", "vlm-transformers", "vlm-mlx-engine", "vlm-vllm-engine", "vlm-vllm-async-engine"],
        help="Backend MinerU à utiliser (défaut : pipeline).",
    )
    parser.add_argument(
        "--skip-mineru", action="store_true",
        help="Ne pas relancer MinerU ; réutiliser une sortie MinerU déjà produite "
             "(nécessite --mineru-output ou une sortie déjà présente sous <output-dir>/mineru_raw).",
    )
    parser.add_argument(
        "--serie-preference", choices=["social", "consolide"], default=DEFAULT_SERIE_PREFERENCE,
        help="Série privilégiée en cas d'égalité de couverture/score entre comptes "
             "consolidés et comptes sociaux (défaut : social).",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Active les logs de niveau DEBUG.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        log.setLevel(logging.DEBUG)

    pdf_path: Path = args.pdf.resolve()
    if not pdf_path.exists():
        log.error("Fichier PDF introuvable : %s", pdf_path)
        return 1

    output_dir = args.output_dir or (Path("output") / pdf_path.stem)
    output_dir = output_dir.resolve()

    try:
        process_pdf(
            pdf_path=pdf_path,
            output_dir=output_dir,
            lang=args.lang,
            backend=args.backend,
            skip_mineru=args.skip_mineru,
            mineru_output_override=(
                args.mineru_output_override.resolve() if args.mineru_output_override else None
            ),
            serie_preference=args.serie_preference,
        )
    except Exception as exc:  # noqa: BLE001 - point d'entrée : on journalise proprement
        log.error("Échec du traitement : %s", exc)
        if args.verbose:
            log.exception("Détail de l'exception :")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())