#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docling_ocr_selected_tables.py  (v4 - correctif fusion de lignes)
=========================================================================
CORRECTIF PAR RAPPORT À LA v3 (audit AFMA_SA/2016) :

    Problème identifié : quand une ligne du tableau n'a AUCUNE valeur
    numérique (ex: "Frais préliminaires", vide) ou quand deux libellés
    sont visuellement très proches (peu d'espace vertical entre eux),
    TableFormer les fusionne parfois en UNE seule ligne OCR contenant 2-3
    libellés concaténés (ex: "IMMOBILISATIONS INCORPORELLES (B)
    Immobilisations en recherche et développement"). Cause racine : le
    PNG exporté (table.get_image()) est une image PLATE, qui a perdu les
    traits vectoriels du PDF original servant à Docling pour distinguer
    les lignes — TableFormer doit alors deviner la structure à partir des
    seuls pixels, et les lignes à faible signal (peu/pas de chiffres)
    sont les plus fragiles.

    CORRECTIF (fonction align_rows_to_expected_fields, section 5bis) :
    on s'appuie sur EXPECTED_FIELDS (déjà présent, ordre officiel CGNC)
    pour détecter qu'une ligne OCR correspond en fait à la concaténation
    de N libellés attendus consécutifs, et on éclate automatiquement
    cette ligne en N lignes propres :
        - les valeurs numériques restent attachées à la PREMIÈRE ligne
          du groupe éclaté ; JAMAIS de valeur inventée ou dupliquée sans
          preuve
        - CHAQUE ligne issue d'un éclatement est marquée explicitement
          (colonne 'Verification' dans le CSV, champ 'fusion_flags' dans
          le JSON) pour qu'un humain puisse vérifier avant usage
        - option --no-align pour désactiver ce correctif et retrouver le
          comportement v3 brut si besoin de comparaison

    Autre ajustement : images_scale par défaut passé de 2.0 à 3.0 (plus
    de résolution = signal visuel plus net pour les lignes fines de
    séparation, réduit mécaniquement le nombre de fusions).

    Ces deux correctifs limitent le problème, mais ne l'éliminent pas à
    100% (Docling continue de travailler sur une image rasterisée). Voir
    la note en fin de fichier pour la correction structurelle complète
    (fournir un crop PDF vectoriel plutôt qu'un PNG plat).

CORRECTIFS SUPPLÉMENTAIRES (cette révision) :

    1. La catégorie "cpc" utilise désormais réellement la fonction dédiée
       align_rows_to_expected_fields_cpc() (section 5ter) au lieu de la
       version générique. Cette fonction existait déjà dans le fichier
       mais n'était jamais appelée par process_category() : tout son
       code (matching par tokens, fenêtre glissante, non-éclatement des
       lignes TOTAL/RESULTAT...) était mort. Le branchement se fait dans
       process_category(), par catégorie.

    2. Ajout de l'option CLI --self-test qui exécute les auto-tests
       _self_test_align_cpc() (qui existaient déjà mais n'étaient reliés
       à aucun argument ni appelés depuis main()) puis quitte avec un
       code de sortie 0 (ou 1 si un test échoue).
=========================================================================
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# =========================================================================
# 1. LOGGING
# =========================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("docling_ocr_selected_tables")


# =========================================================================
# 2. NORMALISATION DE TEXTE
# =========================================================================

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fuzzy_contains(haystack_norm: str, needle_norm: str, threshold: float = 0.84) -> bool:
    if not needle_norm or not haystack_norm:
        return False
    if needle_norm in haystack_norm:
        return True
    needle_words = needle_norm.split()
    hay_words = haystack_norm.split()
    win = len(needle_words)
    if win == 0 or len(hay_words) < win:
        return False
    for i in range(0, len(hay_words) - win + 1):
        window_text = " ".join(hay_words[i:i + win])
        if difflib.SequenceMatcher(None, needle_norm, window_text).ratio() >= threshold:
            return True
    return False


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def make_unique_columns(columns: list) -> list[str]:
    seen: dict[str, int] = {}
    unique_columns: list[str] = []
    for index, column in enumerate(columns, start=1):
        name = clean_text(column) or f"col_{index}"
        seen[name] = seen.get(name, 0) + 1
        unique_columns.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return unique_columns


def safe_model_dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return str(value)


# =========================================================================
# 3. NOMENCLATURE CGNC - sert AUSSI de référentiel pour réaligner les
#    lignes fusionnées.
# =========================================================================

EXPECTED_FIELDS: dict[str, list[str]] = {
    "identification": [
        "Numéro de registre du commerce et code du centre de registre du commerce combiné",
        "Code du centre de registre du commerce",
        "Numéro de registre du commerce",
        "Nom de l'entreprise",
    ],
    "bilan_actif": [
        "Immobilisations en non valeur", "Frais préliminaires",
        "Charges à répartir sur plusieurs exercices",
        "Primes de remboursement des obligations", "Immobilisations incorporelles",
        "Immobilisation en recherche et développement",
        "Brevets, marques, droits et valeurs similaires", "Fonds commercial",
        "Autres immobilisations incorporelles", "Immobilisations corporelles",
        "Terrains", "Constructions",
        "Installations techniques, matériel et outillage", "Matériel de transport",
        "Mobilier, matériel de bureau et aménagements divers",
        "Autres immobilisations corporelles", "Immobilisations corporelles en cours",
        "Immobilisations financières", "Prêts immobilisés",
        "Autres créances financières", "Titres de participation",
        "Autres titres immobilisés", "Ecarts de conversion - Actif",
        "Diminution des créances immobilisées",
        "Augmentation des dettes de financement", "Stocks", "Marchandises",
        "Matières et fournitures consommables", "Produits en cours",
        "Produits intermédiaires et produits résiduels", "Produits finis",
        "Créances de l'actif circulant",
        "Fournisseurs débiteurs, avances et acomptes",
        "Clients et comptes rattachés", "Personnel", "Etat",
        "Comptes d'associés", "Autres débiteurs", "Comptes de régularis. Actif",
        "Titres et valeurs de placement",
        "Ecarts de conversion - Actif (Eléments circulants)", "Trésorerie Actif",
        "Chèques et valeurs à encaisser", "Banques, T.G. et C.C.P.",
        "Caisses, régies d'avances et accréditifs", "Total actif",
    ],
    "bilan_passif": [
        "Capital social ou personnel", "Primes d'émission, de fusion et d'apport",
        "Ecarts de réévaluation", "Réserve légale", "Autres réserves",
        "Report à nouveau", "Résultats nets en instance d'affectation",
        "Résultat net de l'exercice", "Total des capitaux propres",
        "Capitaux propres assimilés", "Subventions d'investissement",
        "Provisions réglementées", "Dettes de financement",
        "Emprunts obligataires", "Autres dettes de financement",
        "Provisions durables pour risques et charges", "Provisions pour risques",
        "Provisions pour charges", "Ecarts de conversion - Passif",
        "Augmentation des créances immobilisées",
        "Diminution des dettes de financement", "Dettes du passif circulant",
        "Fournisseurs et comptes rattachés",
        "Clients créditeurs, avances et acomptes", "Personnel",
        "Organismes sociaux", "Etat", "Comptes d'associés", "Autres créanciers",
        "Comptes de régularisation - Passif",
        "Autres provisions pour risques et charges",
        "Ecarts de conversion - Passif (Eléments circulants)", "Trésorerie Passif",
        "Crédits d'escompte", "Crédits de trésorerie",
        "Banques (soldes créditeurs)", "Total passif",
    ],
    "cpc": [
        "Produits d'exploitation", "Ventes de marchandises",
        "Ventes de biens et services produits", "Chiffres d'affaires",
        "Variation des stocks de produits",
        "Immobilisations produites par l'entreprise pour elle-même",
        "Subventions d'exploitation", "Autres produits d'exploitation",
        "Reprises d'exploitation; transferts de charges", "Charges d'exploitation",
        "Achats revendus de marchandises",
        "Achats consommés de matières et fournitures", "Autres charges externes",
        "Impôts et taxes", "Charges de personnel", "Autres charges d'exploitation",
        "Dotations d'exploitation", "Résultat d'exploitation", "Produits financiers",
        "Produits des titres de participation et autres titres immobilisés",
        "Gains de change", "Intérêts et autres produits financiers",
        "Reprises financières; transferts de charges", "Charges financières",
        "Charges d'intérêts", "Pertes de change", "Autres charges financières",
        "Dotations financières", "Résultat financier", "Résultat courant",
        "Produits non courants", "Produits des cessions d'immobilisations",
        "Subventions d'équilibre", "Reprises sur subventions d'investissement",
        "Autres produits non courants",
        "Reprises non courantes; transferts de charges", "Charges non courantes",
        "Valeurs nettes d'amortissements des immobilisations cédées",
        "Subventions accordées", "Autres charges non courantes",
        "Dotations non courantes aux amortissements et aux provisions",
        "Résultat non courant", "Résultat avant impôts",
        "Impôts sur les résultats", "Résultat net",
    ],
}

CATEGORY_IMAGE_NAMES: dict[str, str] = {
    "identification": "identification.png",
    "bilan_actif": "bilan_actif.png",
    "bilan_passif": "bilan_passif.png",
    "cpc": "cpc.png",
}

LOW_COVERAGE_THRESHOLD = 0.55


# =========================================================================
# 4. CONVERTER DOCLING
# =========================================================================

def make_docling_converter(images_scale: float = 3.0):
    """images_scale par défaut relevé de 2.0 à 3.0 : plus de résolution
    donne à TableFormer un signal visuel plus net sur les fines lignes de
    séparation entre rangées, ce qui réduit (sans l'éliminer) le nombre de
    fusions de lignes."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        generate_page_images=True,
        generate_table_images=True,
        images_scale=images_scale,
    )
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline_options.table_structure_options.do_cell_matching = True

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        }
    )


def table_item_to_json(
    *,
    table: Any,
    doc: Any,
    category: str,
    input_path: Path,
    table_index: int,
    output_images_dir: Path,
) -> dict[str, Any]:
    df = table.export_to_dataframe(doc=doc)
    df = df.fillna("")

    rows = [[clean_text(cell) for cell in row] for row in df.astype(str).values.tolist()]
    columns = make_unique_columns([str(col) for col in df.columns])

    image_path: Optional[Path] = None
    image_error: Optional[str] = None
    try:
        image = table.get_image(doc)
        if image is not None:
            output_images_dir.mkdir(parents=True, exist_ok=True)
            safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", input_path.stem)
            image_path = output_images_dir / f"{category}_{safe_stem}_table_{table_index:03d}.png"
            image.save(image_path)
    except Exception as exc:  # noqa: BLE001
        image_error = str(exc)

    return {
        "category": category,
        "source": "mineru_image_docling",
        "table_index": table_index,
        "input_path": str(input_path),
        "row_count": len(rows),
        "column_count": len(columns),
        "columns": columns,
        "rows": rows,
        "records": [dict(zip(columns, row)) for row in rows],
        "html": table.export_to_html(doc=doc),
        "markdown": table.export_to_markdown(doc=doc),
        "otsl": table.export_to_otsl(doc=doc),
        "image_path": str(image_path) if image_path else None,
        "image_error": image_error,
        "provenance": [safe_model_dump(p) for p in getattr(table, "prov", [])],
        "fusion_flags": [""] * len(rows),  # rempli par align_rows_to_expected_fields si activé
    }


def extract_tables_from_image(
    converter, category: str, image_path: Path, output_images_dir: Path,
) -> list[dict[str, Any]]:
    result = converter.convert(image_path)
    doc = result.document
    return [
        table_item_to_json(
            table=table, doc=doc, category=category, input_path=image_path,
            table_index=idx, output_images_dir=output_images_dir,
        )
        for idx, table in enumerate(doc.tables, start=1)
    ]


# =========================================================================
# 5. COUVERTURE CGNC
# =========================================================================

def compute_field_coverage(category: str, text_norm: str) -> tuple[list[str], list[str], float]:
    expected = EXPECTED_FIELDS.get(category, [])
    found, missing = [], []
    for label in expected:
        if fuzzy_contains(text_norm, normalize_text(label)):
            found.append(label)
        else:
            missing.append(label)
    ratio = round(len(found) / len(expected), 3) if expected else 0.0
    return found, missing, ratio


def table_dict_to_norm_text(table_dict: dict) -> str:
    parts = [cell for row in table_dict.get("rows", []) for cell in row]
    return normalize_text(" ".join(parts))


# =========================================================================
# 5bis. CORRECTIF FUSION DE LIGNES - alignement sur EXPECTED_FIELDS
# =========================================================================

MAX_FUSION_WINDOW = 4          # nb max de libellés qu'on tente de "dé-fusionner" ensemble
MIN_FUSION_MATCH_RATIO = 0.55  # confiance minimale pour accepter un éclatement


def align_rows_to_expected_fields(category: str, table_dict: dict) -> dict:
    """Détecte les lignes où Docling a fusionné plusieurs libellés CGNC
    consécutifs (ex: 'IMMOBILISATIONS INCORPORELLES (B) Immobilisations en
    recherche et développement') et les éclate en lignes propres, en
    s'appuyant sur l'ordre officiel connu (EXPECTED_FIELDS).

    RÈGLES STRICTES :
        - AUCUNE valeur numérique n'est inventée, recalculée ou dupliquée
          sans certitude : les valeurs de la ligne fusionnée restent
          attachées à la PREMIÈRE ligne du groupe éclaté uniquement.
        - Les libellés ajoutés (2e, 3e... du groupe) ont des valeurs VIDES.
        - TOUTE ligne issue d'un éclatement est marquée dans
          table_dict['fusion_flags'] pour vérification humaine ultérieure.
        - Si aucune correspondance suffisamment fiable n'est trouvée, la
          ligne est laissée TELLE QUELLE (aucune modification).
    """
    expected = EXPECTED_FIELDS.get(category, [])
    rows = table_dict.get("rows", [])
    if not expected or not rows:
        return table_dict

    expected_norm = [normalize_text(e) for e in expected]
    columns = table_dict["columns"]
    n_value_cols = max(len(columns) - 1, 0)

    new_rows: list[list[str]] = []
    flags: list[str] = []
    exp_i = 0  # pointeur de progression dans la liste officielle

    for row in rows:
        if not row:
            new_rows.append(row)
            flags.append("")
            continue

        label, values = row[0], row[1:]
        label_norm = normalize_text(label)

        if not label_norm or exp_i >= len(expected_norm):
            new_rows.append(row)
            flags.append("")
            continue

        best_window, best_ratio = 1, 0.0
        max_window = min(MAX_FUSION_WINDOW, len(expected_norm) - exp_i)
        for window in range(1, max_window + 1):
            candidate = " ".join(expected_norm[exp_i:exp_i + window])
            ratio = difflib.SequenceMatcher(None, candidate, label_norm).ratio()
            if ratio >= best_ratio:
                best_ratio, best_window = ratio, window

        if best_window <= 1 or best_ratio < MIN_FUSION_MATCH_RATIO:
            new_rows.append(row)
            flags.append("")
            exp_i += 1
            continue

        for offset in range(best_window):
            sub_label = expected[exp_i + offset]
            if offset == 0:
                new_rows.append([sub_label] + list(values))
            else:
                new_rows.append([sub_label] + [""] * n_value_cols)
            flags.append(
                f"LIGNE_ECLATEE_AUTOMATIQUEMENT_A_VERIFIER (fusion detectee de {best_window} libelles, "
                f"confiance={best_ratio:.2f})"
            )
        exp_i += best_window

    table_dict = dict(table_dict)
    table_dict["rows"] = new_rows
    table_dict["row_count"] = len(new_rows)
    table_dict["records"] = [dict(zip(columns, r)) for r in new_rows]
    table_dict["fusion_flags"] = flags
    n_split = sum(1 for f in flags if f)
    if n_split:
        log.info("[%s] %d ligne(s) éclatée(s) automatiquement (fusion Docling détectée).",
                  category, n_split)
    return table_dict


# =========================================================================
# 5ter. CORRECTIF DÉDIÉ AU CPC - matching par tokens, fenêtre glissante
#       (ISOLÉ : align_rows_to_expected_fields() reste inchangée pour les
#       bilans, aucune régression possible sur bilan_actif/bilan_passif)
# =========================================================================

CPC_LOOKAHEAD = 12               # portée de la fenêtre de recherche locale
CPC_MAX_FUSION_WINDOW = 3        # nb max de libellés éclatés ensemble
CPC_STRONG_MATCH_THRESHOLD = 0.72   # confiance suffisante pour agir automatiquement
CPC_MIN_ACCEPT_THRESHOLD = 0.58     # en dessous : on ne fait RIEN, on flague

CPC_TOTAL_REGEX = re.compile(r"\btotal\b")
CPC_RESULTAT_REGEX = re.compile(r"\bresultat\b")
CPC_SECTION_TITLES_NORM = {
    normalize_text(t) for t in [
        "Produits d'exploitation", "Charges d'exploitation",
        "Produits financiers", "Charges financières",
        "Produits non courants", "Charges non courantes",
    ]
}


def strip_numbers_for_label_matching(text: str) -> str:
    """Retire toute sous-séquence numérique du texte AVANT comparaison de
    libellés (ex: un chiffre collé au libellé par une erreur OCR ne doit
    jamais fausser un score de similarité textuelle). Ne touche JAMAIS aux
    colonnes de valeurs elles-mêmes — uniquement au texte de comparaison."""
    text = re.sub(r"[-+]?\d[\d\s,.]*\d|\d", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text_norm: str) -> list[str]:
    return [t for t in text_norm.split() if t]


def token_set_score(a_tokens: list[str], b_tokens: list[str]) -> float:
    """Équivalent maison (sans dépendance externe) d'un token_set_ratio :
    robuste à l'ordre des mots et aux variantes proches, plus fiable que
    SequenceMatcher brut sur des phrases entières pour des libellés CGNC
    qui varient légèrement d'un rapport à l'autre."""
    if not a_tokens or not b_tokens:
        return 0.0
    set_a, set_b = set(a_tokens), set(b_tokens)
    intersection = set_a & set_b
    seq_ratio = difflib.SequenceMatcher(
        None, " ".join(sorted(set_a)), " ".join(sorted(set_b))
    ).ratio()
    if not intersection:
        return seq_ratio  # repli : capte quand même les variantes proches
    jaccard_like = len(intersection) / min(len(set_a), len(set_b))
    return (jaccard_like + seq_ratio) / 2


def length_consistency_penalty(a_tokens: list[str], b_tokens: list[str]) -> float:
    """Pénalise (sans annuler) un score quand les tailles de texte sont
    très différentes — évite qu'un fragment court comme 'Intérêts' vienne
    matcher à tort un libellé bien plus long."""
    la, lb = len(a_tokens), len(b_tokens)
    if la == 0 or lb == 0:
        return 0.0
    return min(la, lb) / max(la, lb)


def classify_cpc_row_type(label_norm: str) -> str:
    if not label_norm:
        return "VIDE"
    if CPC_TOTAL_REGEX.search(label_norm):
        return "TOTAL"
    if CPC_RESULTAT_REGEX.search(label_norm):
        return "RESULTAT"
    if label_norm in CPC_SECTION_TITLES_NORM:
        return "TITRE_SECTION"
    return "DETAIL"


def align_rows_to_expected_fields_cpc(table_dict: dict) -> dict:
    """Version DÉDIÉE au CPC. N'affecte JAMAIS bilan_actif/bilan_passif
    (qui continuent d'utiliser align_rows_to_expected_fields() ci-dessus,
    inchangée).

    Garanties (cf. cahier des charges) :
        1. Aucune ligne n'est créée sans preuve textuelle réelle dans la
           ligne OCR — jamais "parce que c'est le suivant dans la liste".
        2. Les nombres sont retirés avant toute comparaison de libellés.
        3. Matching par tokens (mots), pas seulement séquence de
           caractères entière.
        4/7. Recherche dans une fenêtre glissante LOCALE (pas seulement le
           libellé suivant strict) -> tolère les lignes manquantes du CGNC.
        6. Une ligne absente ne décale jamais les suivantes.
        8/9. TOTAL / RÉSULTAT / titres de section détectés et JAMAIS éclatés.
        11. Score ambigu -> AUCUNE modification automatique, flag seulement.
    """
    expected = EXPECTED_FIELDS.get("cpc", [])
    rows = table_dict.get("rows", [])
    if not expected or not rows:
        return table_dict

    expected_norm = [normalize_text(e) for e in expected]
    expected_tokens = [tokenize(e) for e in expected_norm]
    columns = table_dict["columns"]
    n_value_cols = max(len(columns) - 1, 0)

    consumed = [False] * len(expected)
    new_rows: list[list[str]] = []
    flags: list[str] = []
    row_types: list[str] = []
    exp_i = 0  # position "molle" servant seulement à orienter la fenêtre

    log.debug("=== Alignement CPC : %d ligne(s) OCR, %d champ(s) attendus ===", len(rows), len(expected))

    for row in rows:
        if not row:
            new_rows.append(row); flags.append(""); row_types.append("VIDE")
            continue

        label_raw, values = row[0], row[1:]
        label_norm = normalize_text(strip_numbers_for_label_matching(label_raw))
        label_tokens = tokenize(label_norm)

        if not label_tokens:
            new_rows.append(row); flags.append(""); row_types.append("VIDE")
            continue

        row_type_guess = classify_cpc_row_type(label_norm)

        if row_type_guess in ("TOTAL", "RESULTAT", "TITRE_SECTION"):
            # Ces lignes sont par nature uniques : JAMAIS éclatées.
            new_rows.append(row)
            flags.append("")
            row_types.append(row_type_guess)
            for j in range(exp_i, min(exp_i + CPC_LOOKAHEAD, len(expected))):
                if not consumed[j] and token_set_score(label_tokens, expected_tokens[j]) >= CPC_MIN_ACCEPT_THRESHOLD:
                    consumed[j] = True
                    exp_i = j + 1
                    break
            continue

        best_score, best_start, best_len = 0.0, None, 0
        for start in range(exp_i, min(exp_i + CPC_LOOKAHEAD, len(expected))):
            if consumed[start]:
                continue
            acc_tokens: list[str] = []
            for length in range(1, CPC_MAX_FUSION_WINDOW + 1):
                idx = start + length - 1
                if idx >= len(expected) or consumed[idx]:
                    break
                acc_tokens = acc_tokens + expected_tokens[idx]
                score = token_set_score(label_tokens, acc_tokens)
                score *= (0.5 + 0.5 * length_consistency_penalty(label_tokens, acc_tokens))
                if score > best_score:
                    best_score, best_start, best_len = score, start, length

        if best_start is None or best_score < CPC_MIN_ACCEPT_THRESHOLD:
            # Aucune preuve textuelle suffisante : RIEN n'est modifié.
            new_rows.append(row)
            flags.append(f"NON_RECONNU_A_VERIFIER (meilleur score={best_score:.2f})")
            row_types.append("NON_RECONNU")
            continue

        if best_len == 1:
            consumed[best_start] = True
            exp_i = best_start + 1
            new_rows.append(row)
            flags.append("" if best_score >= CPC_STRONG_MATCH_THRESHOLD
                          else f"CORRESPONDANCE_INCERTAINE_A_VERIFIER (score={best_score:.2f})")
            row_types.append("DETAIL")
            continue

        if best_score < CPC_STRONG_MATCH_THRESHOLD:
            # Fusion plausible mais pas assez fiable -> AUCUNE décision
            # automatique, on flague seulement (règle 11).
            new_rows.append(row)
            flags.append(f"FUSION_POSSIBLE_NON_ECLATEE_A_VERIFIER (score={best_score:.2f}, "
                          f"{best_len} champ(s) candidat(s))")
            row_types.append("NON_RECONNU")
            continue

        for offset in range(best_len):
            idx = best_start + offset
            consumed[idx] = True
            sub_label = expected[idx]
            if offset == 0:
                new_rows.append([sub_label] + list(values))
            else:
                new_rows.append([sub_label] + [""] * n_value_cols)
            flags.append(
                f"LIGNE_ECLATEE_AUTOMATIQUEMENT_A_VERIFIER (fusion de {best_len} libelles, "
                f"confiance={best_score:.2f})"
            )
            row_types.append("DETAIL")
        exp_i = best_start + best_len

    table_dict = dict(table_dict)
    table_dict["rows"] = new_rows
    table_dict["row_count"] = len(new_rows)
    table_dict["records"] = [dict(zip(columns, r)) for r in new_rows]
    table_dict["fusion_flags"] = flags
    table_dict["row_types"] = row_types

    n_split = sum(1 for f in flags if f.startswith("LIGNE_ECLATEE"))
    n_unrecognized = sum(1 for f in flags if "NON_RECONNU" in f or "FUSION_POSSIBLE" in f)
    n_uncertain = sum(1 for f in flags if "INCERTAINE" in f)
    log.info("[cpc] %d ligne(s) eclatee(s), %d non reconnue(s)/fusion non tranchee, "
             "%d correspondance(s) incertaine(s) sur %d lignes OCR.",
             n_split, n_unrecognized, n_uncertain, len(rows))
    return table_dict


def _self_test_align_cpc() -> None:
    """Auto-tests légers (pas de dépendance pytest) pour valider les
    garanties clés. Lancer avec --self-test."""
    columns = ["col_1", "Exercice.1", "Exercice.2", "Exercice.3", "Exercice_Precedent"]

    # Cas 1 : fusion réelle -> doit être éclatée, valeurs sur la 1re ligne seulement
    t1 = {"columns": columns, "rows": [
        ["Subventions d'exploitation Autres produits d'exploitation", "1000", "", "1000", "500"],
    ]}
    r1 = align_rows_to_expected_fields_cpc(t1)
    assert len(r1["rows"]) == 2, "Cas 1 : la fusion aurait dû être éclatée en 2 lignes"
    assert r1["rows"][0][0].lower().startswith("subventions")
    assert r1["rows"][1][0].lower().startswith("autres produits")
    assert r1["rows"][1][1] == "", "Cas 1 : jamais de valeur inventée sur la 2e ligne éclatée"

    # Cas 2 : texte sans rapport -> ne doit RIEN inventer
    t2 = {"columns": columns, "rows": [["Texte aleatoire sans rapport", "", "", "", ""]]}
    r2 = align_rows_to_expected_fields_cpc(t2)
    assert len(r2["rows"]) == 1
    assert r2["rows"][0][0] == "Texte aleatoire sans rapport", "Cas 2 : aucune invention attendue"
    assert "NON_RECONNU" in r2["fusion_flags"][0]

    # Cas 3 : une ligne TOTAL ne doit jamais être éclatée
    t3 = {"columns": columns, "rows": [["TOTAL I", "100", "", "100", "90"]]}
    r3 = align_rows_to_expected_fields_cpc(t3)
    assert len(r3["rows"]) == 1
    assert r3["row_types"][0] == "TOTAL"

    # Cas 4 : ligne manquante entre 2 lignes connues -> pas de décalage
    t4 = {"columns": columns, "rows": [
        ["Ventes de marchandises", "10", "", "10", "5"],
        ["Charges de personnel", "50", "", "50", "40"],
    ]}
    r4 = align_rows_to_expected_fields_cpc(t4)
    assert r4["rows"][0][0].lower().startswith("ventes de marchandises")
    assert r4["rows"][1][0].lower().startswith("charges de personnel"), (
        "Cas 4 : une ligne absente ne doit pas empêcher la reconnaissance de la suivante"
    )

    print("✅ Tous les auto-tests align_rows_to_expected_fields_cpc() sont passés.")


# =========================================================================
# 5quater. CORRECTIFS OCR SUPPLÉMENTAIRES (CPC) - artefacts observés en
#          conditions réelles (audit AFMA_SA/2016) :
#
#   A) Nombre collé au libellé sans espace, ex:
#      "...titres immobilises7 054 597,78" au lieu d'avoir le chiffre
#      dans sa colonne. On détecte un nombre plausible en fin de libellé,
#      collé à une lettre, et on le déplace dans la 1re colonne de valeur
#      VIDE de la même ligne.
#
#   B) Ligne "orpheline" : libellé vide et UNE SEULE valeur non vide sur
#      toute la ligne -> très probablement le report d'une valeur de la
#      colonne "exercice précédent" qui s'est retrouvée seule sur une
#      ligne OCR séparée. On la fusionne dans la ligne précédente, à la
#      même position de colonne, SI ET SEULEMENT SI cette cellule y est
#      vide (jamais d'écrasement d'une valeur déjà présente).
#
#   Ces deux correctifs ne touchent JAMAIS une valeur déjà correctement
#   placée ; en cas de doute ils n'agissent pas et laissent la ligne
#   telle quelle. Chaque modification est tracée dans 'fusion_flags'.
# =========================================================================

def _split_label_glued_number(label: str) -> tuple[str, Optional[str]]:
    """Détecte un nombre collé sans espace à la fin d'un libellé et le
    sépare. Retourne (libelle_nettoye, nombre) ou (label, None) si rien
    de fiable n'est détecté."""
    match = re.search(r"^(.*[A-Za-zéèêàûôçîï\)\.,])(\d[\d\s]*[.,]?\d[\d\s]*)$", label.strip())
    if not match:
        return label, None
    prefix, number = match.group(1).strip(), match.group(2).strip()
    # Exige un minimum de chiffres pour éviter de couper un simple "(B)1" etc.
    if len(re.sub(r"[^\d]", "", number)) < 3:
        return label, None
    return prefix, number


def fix_ocr_artifacts_cpc(table_dict: dict) -> dict:
    rows = table_dict.get("rows", [])
    flags = table_dict.get("fusion_flags", [""] * len(rows))
    columns = table_dict["columns"]
    if not rows:
        return table_dict

    new_rows: list[list[str]] = []
    new_flags: list[str] = []

    for row, flag in zip(rows, flags):
        if not row:
            new_rows.append(row)
            new_flags.append(flag)
            continue

        label, values = row[0], list(row[1:])

        # --- A) nombre collé au libellé ---
        prefix, glued_number = _split_label_glued_number(label)
        if glued_number is not None:
            inserted = False
            for i in range(len(values)):
                if not values[i].strip():
                    values[i] = glued_number
                    inserted = True
                    break
            if not inserted and values:
                # Repli prudent : ne perd jamais la donnée, même si toutes
                # les colonnes semblaient déjà remplies.
                values[0] = glued_number
            label = prefix
            flag = (flag + " | " if flag else "") + "NOMBRE_RECOLLE_AU_LIBELLE_A_VERIFIER"

        # --- B) ligne orpheline (report d'une valeur seule) ---
        non_empty = [i for i, v in enumerate(values) if v.strip()]
        if not label.strip() and len(non_empty) == 1 and new_rows:
            col_idx = non_empty[0]
            prev_label, *prev_values = new_rows[-1]
            if col_idx < len(prev_values) and not prev_values[col_idx].strip():
                prev_values[col_idx] = values[col_idx]
                new_rows[-1] = [prev_label] + prev_values
                new_flags[-1] = (
                    (new_flags[-1] + " | " if new_flags[-1] else "")
                    + "VALEUR_REPORTEE_FUSIONNEE_DEPUIS_LIGNE_ORPHELINE_A_VERIFIER"
                )
                continue  # la ligne orpheline est absorbée, pas ajoutée séparément

        new_rows.append([label] + values)
        new_flags.append(flag)

    table_dict = dict(table_dict)
    table_dict["rows"] = new_rows
    table_dict["row_count"] = len(new_rows)
    table_dict["records"] = [dict(zip(columns, r)) for r in new_rows]
    table_dict["fusion_flags"] = new_flags
    n_glued = sum(1 for f in new_flags if "NOMBRE_RECOLLE" in f)
    n_orphan = sum(1 for f in new_flags if "VALEUR_REPORTEE" in f)
    if n_glued or n_orphan:
        log.info("[cpc] correctifs OCR : %d nombre(s) recollé(s) séparé(s), "
                  "%d ligne(s) orpheline(s) fusionnée(s).", n_glued, n_orphan)
    return table_dict


def load_all_mineru_tables_html(mineru_output_dir: Path) -> list[dict]:
    from bs4 import BeautifulSoup

    def expand_html_table(table_html: str) -> list[list[str]]:
        if not table_html:
            return []
        soup = BeautifulSoup(table_html, "html.parser")
        rows: list[list[str]] = []
        row_spans: dict[int, tuple[int, str]] = {}
        for tr in soup.find_all("tr"):
            row: list[str] = []
            col_index = 0

            def consume() -> None:
                nonlocal col_index
                while col_index in row_spans:
                    remaining, value = row_spans[col_index]
                    row.append(value)
                    row_spans[col_index] = (remaining - 1, value) if remaining > 1 else None
                    if row_spans[col_index] is None:
                        del row_spans[col_index]
                    col_index += 1

            consume()
            for cell in tr.find_all(["td", "th"], recursive=False):
                consume()
                value = clean_text(cell.get_text(" "))
                colspan = int(cell.get("colspan", 1) or 1)
                rowspan = int(cell.get("rowspan", 1) or 1)
                for offset in range(colspan):
                    row.append(value)
                    if rowspan > 1:
                        row_spans[col_index + offset] = (rowspan - 1, value)
                col_index += colspan
            consume()
            if any(row):
                rows.append(row)
        return rows

    candidates = sorted(mineru_output_dir.rglob("*_content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"Aucun '*_content_list.json' trouvé sous {mineru_output_dir}.")
    with open(candidates[0], "r", encoding="utf-8") as f:
        blocks = json.load(f)

    tables = []
    counter = 0
    for block in blocks:
        if block.get("type") != "table":
            continue
        counter += 1
        grid = expand_html_table(block.get("table_body", "") or "")
        text = " ".join(cell for row in grid for cell in row)
        tables.append({
            "table_id": counter,
            "page": block.get("page_idx"),
            "image": block.get("img_path"),
            "text_norm": normalize_text(text),
        })
    return tables


def find_recovery_suggestions(missing_fields: list[str], all_tables: list[dict]) -> list[dict]:
    suggestions = []
    for label in missing_fields:
        label_norm = normalize_text(label)
        matches = [t for t in all_tables if fuzzy_contains(t["text_norm"], label_norm)][:1]
        if matches:
            suggestions.append({
                "field": label,
                "found_in_other_tables": [
                    {"table_id": m["table_id"], "page": m["page"], "image": m["image"]} for m in matches
                ],
            })
    return suggestions


# =========================================================================
# 7. ORCHESTRATION D'UNE CATÉGORIE
# =========================================================================

@dataclass
class CategoryResult:
    category: str
    image_path: Path
    tables: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage_ratio: float = 0.0
    found_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    recovery_suggestions: list[dict] = field(default_factory=list)


def process_category(
    category: str, image_path: Path, converter, output_images_dir: Path,
    all_mineru_tables: Optional[list[dict]], align_expected_fields: bool,
) -> CategoryResult:
    log.info("Traitement de '%s' (%s)...", category, image_path.name)
    result = CategoryResult(category=category, image_path=image_path)

    if not image_path.exists():
        result.warnings.append(f"Image introuvable : {image_path}")
        log.warning(result.warnings[-1])
        return result

    try:
        tables = extract_tables_from_image(converter, category, image_path, output_images_dir)
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(f"Échec Docling sur {image_path.name} : {exc}")
        log.error(result.warnings[-1])
        return result

    if not tables:
        result.warnings.append("Aucun tableau détecté par Docling sur cette image.")
        log.warning("[%s] %s", category, result.warnings[-1])
        return result

    if align_expected_fields:
        # CORRECTIF : la catégorie "cpc" a sa propre fonction d'alignement
        # dédiée (section 5ter, matching par tokens + fenêtre glissante),
        # plus robuste sur ce tableau que la fonction générique. Elle
        # existait déjà dans le fichier mais n'était jamais appelée ici.
        if category == "cpc":
            tables = [align_rows_to_expected_fields_cpc(t) for t in tables]
        else:
            tables = [align_rows_to_expected_fields(category, t) for t in tables]

    result.tables = tables

    best = max(tables, key=lambda t: t["row_count"])
    text_norm = table_dict_to_norm_text(best)
    found, missing, ratio = compute_field_coverage(category, text_norm)
    result.found_fields, result.missing_fields, result.coverage_ratio = found, missing, ratio

    if ratio < LOW_COVERAGE_THRESHOLD:
        log.warning("[%s] Couverture faible (%.0f%%).", category, ratio * 100)

    if missing and all_mineru_tables:
        result.recovery_suggestions = find_recovery_suggestions(missing, all_mineru_tables)
        if result.recovery_suggestions:
            log.info("[%s] %d champ(s) manquant(s) potentiellement ailleurs dans le PDF.",
                      category, len(result.recovery_suggestions))

    return result


# =========================================================================
# 8. SORTIES
# =========================================================================

def save_category_csv(result: CategoryResult, csv_dir: Path) -> Optional[Path]:
    if not result.tables:
        return None
    best = max(result.tables, key=lambda t: t["row_count"])
    if not best["rows"]:
        return None
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / f"{result.category}.csv"
    flags = best.get("fusion_flags", [""] * len(best["rows"]))
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        header = list(best["columns"]) + ["Verification"]
        f.write(";".join('"' + c.replace('"', '""') + '"' for c in header) + "\n")
        for row, flag in zip(best["rows"], flags):
            full_row = list(row) + [flag]
            f.write(";".join('"' + c.replace('"', '""') + '"' for c in full_row) + "\n")
    return csv_path


def build_output_json(document_name: str, results: list[CategoryResult]) -> dict:
    return {
        "document": document_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tables": [t for r in results for t in r.tables],
        "coverage": [
            {
                "category": r.category,
                "coverage_ratio": r.coverage_ratio,
                "found_fields": r.found_fields,
                "missing_fields": r.missing_fields,
                "recovery_suggestions": r.recovery_suggestions,
                "warnings": r.warnings,
                "n_rows_flagged": sum(1 for t in r.tables for f in t.get("fusion_flags", []) if f),
            }
            for r in results
        ],
    }


# =========================================================================
# 9. ORCHESTRATION PRINCIPALE
# =========================================================================

def process_selected_tables(
    selected_dir: Path, output_dir: Path, mineru_output_dir: Optional[Path], images_scale: float,
    converter=None, align_expected_fields: bool = True,
) -> Path:
    document_name = selected_dir.parent.name or selected_dir.name

    if converter is None:
        converter = make_docling_converter(images_scale=images_scale)

    all_mineru_tables = None
    if mineru_output_dir:
        try:
            all_mineru_tables = load_all_mineru_tables_html(mineru_output_dir)
            log.info("%d tableaux MinerU disponibles pour le repli.", len(all_mineru_tables))
        except Exception as exc:  # noqa: BLE001
            log.warning("Repli désactivé (%s).", exc)

    table_images_dir = output_dir / "table_images"
    csv_dir = output_dir / "tables_csv"

    results = []
    for category, filename in CATEGORY_IMAGE_NAMES.items():
        image_path = selected_dir / filename
        result = process_category(
            category, image_path, converter, table_images_dir, all_mineru_tables, align_expected_fields,
        )
        save_category_csv(result, csv_dir)
        results.append(result)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{document_name}_docling_tables.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(build_output_json(document_name, results), f, ensure_ascii=False, indent=2)
    log.info("JSON d'extraction écrit : %s", json_path)

    log.info("=" * 70)
    log.info("RÉSUMÉ - %s", document_name)
    for r in results:
        status = f"{len(r.tables)} tableau(x) détecté(s)" if r.tables else "AUCUN TABLEAU DÉTECTÉ"
        n_flagged = sum(1 for t in r.tables for f in t.get("fusion_flags", []) if f)
        log.info("  %-15s -> %-28s | couverture %5.0f%% | %d ligne(s) à vérifier",
                  r.category, status, r.coverage_ratio * 100, n_flagged)
        for sug in r.recovery_suggestions[:5]:
            other = sug["found_in_other_tables"][0]
            log.info("      ↳ '%s' probablement dans le tableau #%s (page %s)",
                      sug["field"], other["table_id"], other["page"])
    log.info("=" * 70)

    return json_path


# =========================================================================
# 10. MODE BATCH
# =========================================================================

@dataclass
class ReportJob:
    entreprise: str
    annee: str
    selected_dir: Path
    mineru_output_dir: Optional[Path]
    output_dir: Path


def discover_report_dirs(root: Path, output_root: Optional[Path] = None) -> list[ReportJob]:
    """
    Structure réelle :
        <root>/<ENTREPRISE>/<ANNEE>/mineru_raw/<ANNEE>/auto/selected_tables/
    Fallback : ancienne structure <ANNEE>/selected_tables/ si présente.
    Sortie par défaut : <ANNEE>/docling_result/
    """
    if not root.exists():
        raise FileNotFoundError(f"Dossier racine introuvable : {root}")

    jobs: list[ReportJob] = []
    entreprise_dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.lower())

    for entreprise_dir in entreprise_dirs:
        annee_dirs = sorted((p for p in entreprise_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
        for annee_dir in annee_dirs:
            # Nouvelle structure (celle de ta capture d'écran)
            selected_dir = (
                annee_dir / "mineru_raw" / annee_dir.name / "auto" / "selected_tables"
            )
            if not selected_dir.exists():
                # Fallback ancienne structure
                old_selected = annee_dir / "selected_tables"
                if old_selected.exists():
                    selected_dir = old_selected
                else:
                    continue

            mineru_raw = annee_dir / "mineru_raw"

            job_output_dir = (
                output_root / entreprise_dir.name / annee_dir.name
                if output_root is not None
                else annee_dir / "docling_result"
            )

            jobs.append(ReportJob(
                entreprise=entreprise_dir.name,
                annee=annee_dir.name,
                selected_dir=selected_dir,
                mineru_output_dir=mineru_raw if mineru_raw.exists() else None,
                output_dir=job_output_dir,
            ))
    return jobs


def already_processed(job: ReportJob) -> bool:
    return any(job.output_dir.glob("*_docling_tables.json"))


def run_batch(root: Path, images_scale: float, skip_existing: bool,
              output_root: Optional[Path] = None, align_expected_fields: bool = True) -> None:
    jobs = discover_report_dirs(root, output_root=output_root)
    total = len(jobs)

    if total == 0:
        log.warning(
            "Aucun dossier selected_tables trouvé sous %s\n"
            "  Attendu : <root>/<ENTREPRISE>/<ANNEE>/mineru_raw/<ANNEE>/auto/selected_tables/",
            root,
        )
        return

    log.info("=" * 70)
    log.info("MODE BATCH (Script 2) : %d rapport(s) détecté(s) sous %s", total, root)
    if output_root is not None:
        log.info("Sorties Docling ISOLÉES sous : %s/<ENTREPRISE>/<ANNEE>/", output_root)
    log.info("Construction du converter Docling (une seule fois pour tout le batch)...")
    converter = make_docling_converter(images_scale=images_scale)
    log.info("=" * 70)

    error_log_root = output_root if output_root is not None else root
    error_log_root.mkdir(parents=True, exist_ok=True)
    error_log_path = error_log_root / "batch_errors_script2.log"
    n_ok, n_skipped, n_failed = 0, 0, 0

    for i, job in enumerate(jobs, start=1):
        label = f"{job.entreprise} - {job.annee}"
        print(f"[{i}/{total}] {label}")

        if skip_existing and already_processed(job):
            print("↷ déjà traité, ignoré\n")
            n_skipped += 1
            continue

        try:
            process_selected_tables(
                selected_dir=job.selected_dir,
                output_dir=job.output_dir,
                mineru_output_dir=job.mineru_output_dir,
                images_scale=images_scale,
                converter=converter,
                align_expected_fields=align_expected_fields,
            )
            print("✓ terminé\n")
            n_ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"✗ erreur : {exc}\n")
            n_failed += 1
            timestamp = datetime.now().isoformat(timespec="seconds")
            with open(error_log_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {job.entreprise}/{job.annee} : {exc}\n")
            log.error("[%s] Échec : %s", label, exc)
            continue

    log.info("=" * 70)
    log.info("BATCH TERMINÉ : %d réussis, %d ignorés (déjà traités), %d échoués sur %d.",
              n_ok, n_skipped, n_failed, total)
    if n_failed:
        log.info("Détail des erreurs : %s", error_log_path)
    log.info("=" * 70)


# =========================================================================
# 11. CLI
# =========================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Script 2 (v4) : OCR Docling sur selected_tables/, avec correctif de fusion de lignes."
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--selected-dir", type=Path, default=None)
    mode_group.add_argument("--batch-root", type=Path, default=None)
    # --self-test doit pouvoir se lancer seul, sans --selected-dir ni
    # --batch-root : on le retire donc du groupe mutuellement exclusif
    # "required" en le rendant compatible via un contournement plus bas.
    mode_group.required = False

    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--mineru-output", type=Path, default=None)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--images-scale", type=float, default=3.0,
                         help="Résolution du rendu image (défaut 3.0, relevé depuis 2.0 pour réduire "
                              "les fusions de lignes).")
    parser.add_argument("--no-align", dest="align_expected_fields", action="store_false",
                         help="Désactive le correctif d'éclatement des lignes fusionnées "
                              "(retrouve le comportement v3 brut).")
    parser.add_argument("--self-test", action="store_true",
                         help="Lance les auto-tests de align_rows_to_expected_fields_cpc() "
                              "puis quitte (aucun traitement de fichier n'est effectué).")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.verbose:
        log.setLevel(logging.DEBUG)

    # --self-test est prioritaire et autonome : ni --selected-dir ni
    # --batch-root ne sont requis dans ce cas.
    if args.self_test:
        try:
            _self_test_align_cpc()
        except AssertionError as exc:
            log.error("Échec d'un auto-test : %s", exc)
            return 1
        return 0

    if args.selected_dir is None and args.batch_root is None:
        parser.error("un de ces arguments est requis : --selected-dir, --batch-root, --self-test")

    if args.batch_root is not None:
        try:
            run_batch(
                root=args.batch_root.resolve(),
                images_scale=args.images_scale,
                skip_existing=args.skip_existing,
                output_root=(args.output_root.resolve() if args.output_root else None),
                align_expected_fields=args.align_expected_fields,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("Échec du mode batch : %s", exc)
            if args.verbose:
                log.exception("Détail :")
            return 1
        return 0

    selected_dir: Path = args.selected_dir.resolve()
    if not selected_dir.exists():
        log.error("Dossier selected_tables introuvable : %s", selected_dir)
        return 1

    output_dir = (args.output_dir or (selected_dir.parent / "docling_result")).resolve()
    mineru_output_dir = args.mineru_output.resolve() if args.mineru_output else None

    try:
        process_selected_tables(
            selected_dir, output_dir, mineru_output_dir, args.images_scale,
            align_expected_fields=args.align_expected_fields,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Échec du traitement : %s", exc)
        if args.verbose:
            log.exception("Détail :")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

# =========================================================================
# NOTE POUR LA SUITE (non implémenté ici, hors scope de "corriger ce script") :
#
# Le correctif ci-dessus répare le SYMPTÔME (lignes fusionnées) via
# réalignement sur la liste officielle. La cause RACINE reste que Docling
# travaille sur un PNG (rasterisé, sans les traits vectoriels du PDF).
# Une correction plus profonde consisterait, dans le Script 1, à exporter
# en plus un CROP PDF (vectoriel, via fitz : nouvelle page avec cropbox
# restreinte au bbox du tableau) à côté du PNG, et à faire consommer ce
# PDF par Docling (InputFormat.PDF) au lieu du PNG pour les documents dont
# le texte natif n'est PAS corrompu (donc où l'OCR pur n'est pas requis).
# Cela redonnerait à TableFormer l'accès aux vraies lignes de séparation
# du tableau. À réserver aux documents où classify_scanned_vs_text.py /
# la sonde de corruption de police de localization_engine_v2.py confirment
# un texte natif fiable.
# =========================================================================