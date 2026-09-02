#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reprocess_from_existing_mineru.py
================================================================================
Reapplique la logique CORRIGEE de mineru_extract_tables.py (fix "total
actif/passif", fusion des bilans coupes en 2 blocs, detection renforcee
social/consolide) SANS RELANCER MINERU.

Ne fait AUCUN appel a MinerU, aucun OCR : relit uniquement les
*_content_list.json deja produits par un run precedent (qui contiennent
deja le HTML des tableaux, les captions/footnotes, et les chemins vers
les images PNG deja extraites). Cout ~identique a l'audit : quelques
secondes par document, meme sur plusieurs centaines de PDF.

Usage :
    # Parcourt tout un dossier racine (a n'importe quelle profondeur) a la
    # recherche de *_content_list.json deja existants, et ecrit les
    # *_tables_analysis.json + selected_tables/*.png corriges A COTE
    # (meme dossier que le content_list.json trouve) :
    python reprocess_from_existing_mineru.py --root-dir /chemin/vers/output --in-place

    # Ou dans un dossier de sortie separe, un sous-dossier par document :
    python reprocess_from_existing_mineru.py --root-dir /chemin/vers/output \\
        --output-root /chemin/vers/output_corrige
"""

import argparse
import json
from pathlib import Path

from mineru_extract_tables import (
    load_content_blocks,
    build_table_candidates,
    detect_serie_context,
    score_all_candidates,
    repair_partial_bilan_tables,
    add_neighbor_coherence_reasoning,
    select_coherent_serie,
    mark_selection,
    build_output_json,
    export_selected_images,
    DEFAULT_SERIE_PREFERENCE,
    log,
)


def reprocess_one(content_list_path: Path, output_dir: Path, serie_preference: str) -> None:
    """Rejoue les etapes B a F du pipeline pour un content_list.json deja
    produit, sans jamais toucher a MinerU."""
    pdf_stem = content_list_path.name.replace("_content_list.json", "")
    base_dir = content_list_path.parent  # les img_path de content_list.json sont relatifs a ce dossier

    blocks = load_content_blocks(content_list_path)
    candidates = build_table_candidates(blocks, base_dir)

    if not candidates:
        print(f"[IGNORE] {pdf_stem} : aucun tableau detecte dans {content_list_path}")
        return

    detect_serie_context(blocks, candidates)
    score_all_candidates(candidates)
    repair_partial_bilan_tables(candidates)
    add_neighbor_coherence_reasoning(candidates)

    chosen_serie, selection = select_coherent_serie(candidates, serie_preference)
    mark_selection(candidates, selection, chosen_serie)

    output_json = build_output_json(pdf_stem, content_list_path.parent, candidates, chosen_serie, selection)

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{pdf_stem}_tables_analysis.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)

    export_selected_images(selection, output_dir / "selected_tables")

    print(f"[OK] {pdf_stem} -> {json_path}  (serie retenue: {chosen_serie})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reapplique la logique corrigee sans relancer MinerU (reutilise content_list.json existants)."
    )
    parser.add_argument(
        "--root-dir", required=True, type=Path,
        help="Dossier racine ou chercher recursivement les *_content_list.json deja produits par un run MinerU precedent.",
    )
    parser.add_argument(
        "--in-place", action="store_true",
        help="Ecrit le JSON et selected_tables/ corriges a cote du content_list.json trouve "
             "(meme dossier). Ecrase les anciens fichiers du meme nom.",
    )
    parser.add_argument(
        "--output-root", type=Path, default=None,
        help="Si --in-place n'est pas utilise : dossier racine ou creer un sous-dossier "
             "par document (par defaut : ./output_corrige/<nom_pdf>/).",
    )
    parser.add_argument(
        "--serie-preference", choices=["social", "consolide"], default=DEFAULT_SERIE_PREFERENCE,
        help="Serie privilegiee en cas d'egalite (defaut : social).",
    )
    args = parser.parse_args()

    content_lists = sorted(args.root_dir.rglob("*_content_list.json"))
    print(f"{len(content_lists)} fichier(s) *_content_list.json deja existants trouves sous {args.root_dir}")
    if not content_lists:
        print("Aucun content_list.json trouve : verifie --root-dir (il doit pointer vers "
              "le dossier qui contient les sorties MinerU deja produites, ex: le dossier "
              "passe en --output-dir ou --mineru-output lors du run original).")
        return 1

    for cl_path in content_lists:
        pdf_stem = cl_path.name.replace("_content_list.json", "")
        if args.in_place:
            output_dir = cl_path.parent
        else:
            output_dir = (args.output_root or Path("output_corrige")) / pdf_stem
        try:
            reprocess_one(cl_path, output_dir, args.serie_preference)
        except Exception as exc:  # noqa: BLE001
            log.error("Echec sur %s : %s", cl_path, exc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
