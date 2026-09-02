#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_selected_tables.py
================================================================================
Verification LEGERE des tableaux deja selectionnes par mineru_extract_tables.py.
Ne relance RIEN (pas de MinerU, pas d'OCR) -- lit uniquement les
*_tables_analysis.json deja produits.

FIX (suite a verification manuelle par l'utilisateur, cas CASH_PLUS_S.A
2025) : le flag PARTIAL_TABLE base sur "total actif"/"total passif" avait
des faux positifs ET ratait le vrai bug trouve manuellement -- un
sous-tableau (ex: "Immobilisations" seul) selectionne A LA PLACE du bilan
complet, independamment de toute histoire de serie sociale/consolidee.
Remplace par NARROW_SUBTABLE : verifie la presence d'AU MOINS UNE des 3
grandes sections structurantes d'un bilan complet (immobilise, circulant,
tresorerie) -- un sous-tableau de detail (immobilisations seules, dettes
seules...) n'en couvre typiquement AUCUNE explicitement, meme s'il scope
haut sur des mots-cles de detail.

Usage :
    python audit_selected_tables.py --output-dir /chemin/vers/output
"""

import argparse
import csv
import json
from pathlib import Path

LOW_CONFIDENCE_THRESHOLD = 0.5
AMBIGUOUS_SCORE_MARGIN = 8
FEW_KEYYWORDS_THRESHOLD = 2
REQUIRED_CATEGORIES = ["identification", "bilan_actif", "bilan_passif", "cpc"]

# FIX : remplace REQUIRED_TOTAL_KEYWORDS (faux positifs sur "total actif").
# Un bilan_actif COMPLET couvre normalement au moins 2 des 3 grandes
# sections structurantes ; un sous-tableau de detail (immobilisations
# seules, comme le cas CASH_PLUS_S.A trouve manuellement) n'en couvre
# typiquement qu'aucune -- ces libelles de section sont les TITRES des
# grands blocs du bilan, pas des totaux de bas de page (donc moins sujets
# aux variantes de formulation "total de l'actif" vs "total actif").
STRUCTURAL_SECTION_KEYWORDS = {
    "bilan_actif": ["actif immobilise", "actif circulant", "tresorerie actif"],
    "bilan_passif": ["capitaux propres", "dettes de financement",
                      "passif circulant", "tresorerie passif"],
    "cpc": ["compte de produits et charges", "produits d exploitation",
            "charges d exploitation", "resultat d exploitation"],
}
MIN_STRUCTURAL_SECTIONS = 1  # au moins 1 grande section presente, sinon suspect


def audit_one_json(json_path: Path) -> list[dict]:
    """Analyse un *_tables_analysis.json et retourne la liste des lignes a
    risque (une par categorie suspecte), vide si tout semble correct."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [{"fichier": str(json_path), "categorie": "N/A", "flags": f"JSON_ILLISIBLE: {exc}"}]

    tables_by_id = {t["table_id"]: t for t in data.get("tables", [])}
    selection = data.get("selection", {})
    document = data.get("document", json_path.stem)
    detected_series = data.get("detected_series", [])
    selected_serie = data.get("selected_serie", "")

    real_series_found = [s for s in detected_series if s in ("social", "consolide")]
    multi_serie = len(set(real_series_found)) > 1

    rows = []
    for category in REQUIRED_CATEGORIES:
        table_id = selection.get(category)

        if table_id is None:
            rows.append({
                "fichier": str(json_path), "document": document, "categorie": category,
                "table_id": "", "confidence": "", "serie_choisie": selected_serie,
                "series_detectees": ",".join(detected_series), "flags": "NON_TROUVE",
            })
            continue

        table = tables_by_id.get(table_id)
        if table is None:
            rows.append({
                "fichier": str(json_path), "document": document, "categorie": category,
                "table_id": table_id, "confidence": "", "serie_choisie": selected_serie,
                "series_detectees": ",".join(detected_series), "flags": "TABLE_ID_INCOHERENT",
            })
            continue

        flags = []

        if table.get("confidence", 0) < LOW_CONFIDENCE_THRESHOLD:
            flags.append("LOW_CONFIDENCE")

        matched = table.get("matched_keywords", [])
        if len(matched) < FEW_KEYYWORDS_THRESHOLD:
            flags.append("FEW_KEYWORDS")

        reasoning_list = table.get("reasoning", [])
        reasoning = " ".join(reasoning_list)

        if "Structure HTML compatible" not in reasoning:
            flags.append("NOT_TABULAR")

        # FIX principal : sous-tableau de detail selectionne a la place du
        # bilan complet (cas trouve manuellement : "Immobilisations" seul
        # au lieu de bilan_actif entier).
        structural_kw = STRUCTURAL_SECTION_KEYWORDS.get(category)
        if structural_kw:
            n_sections = sum(1 for kw in structural_kw if kw in matched)
            if n_sections < MIN_STRUCTURAL_SECTIONS:
                flags.append(
                    f"NARROW_SUBTABLE(aucune grande section detectee parmi: {'/'.join(structural_kw)} "
                    f"-- probablement un sous-tableau de detail, pas le bilan complet)"
                )

        if "ATTENTION" in reasoning and "PARTIEL" in reasoning:
            flags.append("PARTIAL_UNRESOLVED(voir raisonnement dans le JSON source)")

        if "ATTENTION" in reasoning and "serie forc" in reasoning.lower():
            flags.append("SERIE_CONFLICT(contexte vs contenu du tableau, voir raisonnement)")

        all_scores = table.get("all_scores", {})
        own_score = all_scores.get(category, 0)
        competitors = {k: v for k, v in all_scores.items() if k != category and k != "autre"}
        if competitors:
            best_competitor, best_competitor_score = max(competitors.items(), key=lambda kv: kv[1])
            if own_score - best_competitor_score <= AMBIGUOUS_SCORE_MARGIN:
                flags.append(f"AMBIGUOUS_SCORE(vs {best_competitor}={best_competitor_score})")
            if best_competitor_score > own_score:
                flags.append(f"CROSS_SIGNAL(gagnant={category}:{own_score}, "
                              f"plus_fort={best_competitor}:{best_competitor_score})")

        if multi_serie:
            flags.append(f"MULTI_SERIE_AMBIGUOUS(choisi={selected_serie}, detectees={real_series_found})")

        if flags:
            rows.append({
                "fichier": str(json_path), "document": document, "categorie": category,
                "table_id": table_id, "confidence": table.get("confidence", ""),
                "serie_choisie": selected_serie, "series_detectees": ",".join(detected_series),
                "flags": "; ".join(flags),
            })

    return rows


def main():
    parser = argparse.ArgumentParser(description="Audit leger des tableaux selectionnes (aucun re-traitement)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--csv-out", type=Path, default=Path("audit_report.csv"))
    args = parser.parse_args()

    json_files = sorted(args.output_dir.rglob("*_tables_analysis.json"))
    print(f"{len(json_files)} fichiers *_tables_analysis.json trouves.")

    all_flagged_rows = []
    for jp in json_files:
        all_flagged_rows.extend(audit_one_json(jp))

    if not all_flagged_rows:
        print("Aucune entree a risque detectee.")
        return

    fieldnames = ["fichier", "document", "categorie", "table_id", "confidence",
                  "serie_choisie", "series_detectees", "flags"]
    with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_flagged_rows)

    print(f"{len(all_flagged_rows)} entrees a risque -> {args.csv_out.resolve()}")

    from collections import Counter
    flag_counter = Counter()
    for row in all_flagged_rows:
        for f in row["flags"].split("; "):
            flag_counter[f.split("(")[0]] += 1
    print("\nRepartition des flags :")
    for flag, count in flag_counter.most_common():
        print(f"  {flag}: {count}")


if __name__ == "__main__":
    main()