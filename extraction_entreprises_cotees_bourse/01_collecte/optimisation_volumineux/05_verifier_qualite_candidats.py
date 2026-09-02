#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_candidates_quality.py  (v2 - ciblé sur les PDF d'1 seule page)
=========================================================================
LEÇON APPRISE (v1) : l'heuristique texte (comptage de caractères/chiffres)
donnait de FAUX suspects sur des PDF de plusieurs pages qui contiennent
pourtant bien les tableaux Bilan/CPC (vérifié manuellement par l'utilisateur).
Les PDF >1 page sont donc considérés FIABLES par défaut, sans analyse.
 
Le seul cas réellement ambigu, ce sont les PDF D'UNE SEULE PAGE : certains
contiennent un vrai Bilan/CPC condensé sur 1 page, d'autres ne sont qu'un
communiqué renvoyant vers un site web. Et certains sont des SCANS (aucun
texte extractible), ce qui rend toute heuristique texte aveugle.
 
Stratégie v2 (rapide, PAS d'OCR) :
    - n_pages > 1                          -> OK_MULTIPAGE (confiance, pas d'analyse)
    - n_pages == 1 ET signal texte fort     -> OK_AUTO (mots-clés + tableau détectés)
    - n_pages == 1 ET signal faible/absent  -> A_VERIFIER : on génère une image
                                                PNG de cette page unique dans
                                                A_VERIFIER_VISUELLEMENT/ pour que
                                                l'utilisateur tranche en un coup d'œil
 
Ne modifie RIEN dans Rapports/ ni les PDF eux-mêmes. Produit un CSV +
un dossier d'images pour les cas ambigus.
 
Usage :
    python verify_candidates_quality.py --recap smart_test_output/RECAP_GLOBAL.csv
 
Sorties :
    smart_test_output/QUALITY_CHECK.csv
    smart_test_output/A_VERIFIER_VISUELLEMENT/<ENTREPRISE>_<ANNEE>.png
=========================================================================
"""
 
from __future__ import annotations
 
import argparse
import csv
import re
from pathlib import Path
 
import fitz  # PyMuPDF
 
# ====================== HEURISTIQUES (utilisées SEULEMENT sur les PDF 1 page) ======================
 
FINANCIAL_KEYWORDS = [
    "bilan actif", "bilan passif", "total actif", "total passif",
    "compte de produits et charges", "chiffre d affaires", "chiffre d'affaires",
    "resultat net", "résultat net", "capitaux propres", "actif circulant",
    "passif circulant", "tresorerie actif", "trésorerie actif",
    "tresorerie passif", "trésorerie passif", "immobilisations",
    "produits d exploitation", "produits d'exploitation",
    "charges d exploitation", "charges d'exploitation",
]
 
ANNOUNCEMENT_PATTERNS = [
    "disponible sur son site internet",
    "disponible sur le site internet",
    "est aujourd hui disponible",
    "veuillez consulter notre site",
    "consultable sur le site",
    "telechargeable sur",
]
 
RENDER_ZOOM = 2.5  # résolution de l'image générée pour vérification visuelle
 
 
def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[àáâãäå]', 'a', text)
    text = re.sub(r'[èéêë]', 'e', text)
    text = re.sub(r'[ìíîï]', 'i', text)
    text = re.sub(r'[òóôõö]', 'o', text)
    text = re.sub(r'[ùúûü]', 'u', text)
    text = re.sub(r'ç', 'c', text)
    return text
 
 
def render_page_as_png(doc: fitz.Document, page_index: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page = doc[page_index]
    pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM))
    pix.save(str(out_path))
 
 
def analyze_single_page_pdf(doc: fitz.Document, entreprise: str, annee: str, review_dir: Path) -> dict:
    """N'est appelé QUE pour les PDF d'une seule page."""
    page = doc[0]
    text = page.get_text()
    text_norm = normalize_text(text)
    n_chars = len(text_norm.strip())
 
    try:
        n_tables = len(page.find_tables().tables)
    except Exception:
        n_tables = 0
 
    kw_hits = [kw for kw in FINANCIAL_KEYWORDS if normalize_text(kw) in text_norm]
    announcement_hits = [p for p in ANNOUNCEMENT_PATTERNS if normalize_text(p) in text_norm]
 
    # Signal fort et sans ambiguïté : au moins 1 tableau détecté ET au moins
    # 1 mot-clé financier -> on fait confiance, pas besoin d'image.
    if n_tables >= 1 and len(kw_hits) >= 1:
        return {
            "n_chars": n_chars, "n_tables_detected": n_tables,
            "keywords_found": ", ".join(kw_hits),
            "verdict": "OK_AUTO",
            "raisons": f"{n_tables} tableau(x) détecté(s) + {len(kw_hits)} mot(s)-clé(s) financier(s)",
            "image_verification": "",
        }
 
    # Cas clairement un communiqué vide (motif explicite trouvé, aucun mot-clé financier)
    if announcement_hits and len(kw_hits) == 0:
        img_path = review_dir / f"{entreprise}_{annee}.png"
        render_page_as_png(doc, 0, img_path)
        return {
            "n_chars": n_chars, "n_tables_detected": n_tables,
            "keywords_found": "",
            "verdict": "SUSPECT_ANNONCE",
            "raisons": f"Motif de communiqué détecté ('{announcement_hits[0]}'), aucun mot-clé financier",
            "image_verification": str(img_path),
        }
 
    # Tout le reste (y compris texte quasi vide -> probable scan) : ambigu,
    # on génère l'image pour vérification visuelle plutôt que de deviner.
    img_path = review_dir / f"{entreprise}_{annee}.png"
    render_page_as_png(doc, 0, img_path)
    scan_probable = n_chars < 50
    return {
        "n_chars": n_chars, "n_tables_detected": n_tables,
        "keywords_found": ", ".join(kw_hits),
        "verdict": "A_VERIFIER",
        "raisons": ("Probable scan (texte quasi vide)" if scan_probable
                    else f"Signal ambigu : {len(kw_hits)} mot(s)-clé(s), {n_tables} tableau(x)"),
        "image_verification": str(img_path),
    }
 
 
def main():
    parser = argparse.ArgumentParser(
        description="Vérifie la qualité des candidats téléchargés, en se concentrant "
                     "uniquement sur les PDF d'une seule page (les autres sont fiables)."
    )
    parser.add_argument("--recap", type=Path, default=Path("smart_test_output/RECAP_GLOBAL.csv"))
    parser.add_argument("--out", type=Path, default=Path("smart_test_output/QUALITY_CHECK.csv"))
    parser.add_argument("--review-dir", type=Path, default=Path("smart_test_output/A_VERIFIER_VISUELLEMENT"))
    args = parser.parse_args()
 
    if not args.recap.exists():
        print(f"❌ Fichier introuvable : {args.recap}")
        return
 
    with open(args.recap, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
 
    downloaded = [r for r in rows if r.get("Statut") == "candidat_telecharge" and r.get("Fichier_sortie")]
    print(f"🔍 Analyse de {len(downloaded)} candidat(s) téléchargé(s)...")
 
    results = []
    n_skipped_multipage = 0
    n_analyzed_1page = 0
 
    for r in downloaded:
        entreprise, annee = r["Entreprise"], r["Annee"]
        pdf_path = Path(r["Fichier_sortie"])
 
        if not pdf_path.exists():
            results.append({
                "Entreprise": entreprise, "Annee": annee,
                "Pages_locales_originales": r.get("Pages_locales", ""),
                "Pages_candidat": r.get("Pages_candidat", ""),
                "n_chars": None, "n_tables_detected": None, "keywords_found": "",
                "verdict": "FICHIER_INTROUVABLE", "raisons": str(pdf_path),
                "image_verification": "", "Titre_candidat": r.get("Titre_candidat", ""),
                "Fichier_candidat": r.get("Fichier_sortie", ""),
            })
            continue
 
        try:
            doc = fitz.open(str(pdf_path))
        except Exception as exc:
            results.append({
                "Entreprise": entreprise, "Annee": annee,
                "Pages_locales_originales": r.get("Pages_locales", ""),
                "Pages_candidat": r.get("Pages_candidat", ""),
                "n_chars": None, "n_tables_detected": None, "keywords_found": "",
                "verdict": "ERREUR_LECTURE", "raisons": str(exc),
                "image_verification": "", "Titre_candidat": r.get("Titre_candidat", ""),
                "Fichier_candidat": r.get("Fichier_sortie", ""),
            })
            continue
 
        n_pages = doc.page_count
 
        if n_pages > 1:
            # Validé manuellement par l'utilisateur : fiable, pas d'analyse.
            n_skipped_multipage += 1
            analysis = {
                "n_chars": None, "n_tables_detected": None, "keywords_found": "",
                "verdict": "OK_MULTIPAGE", "raisons": f"{n_pages} pages - confiance (validé manuellement)",
                "image_verification": "",
            }
        else:
            n_analyzed_1page += 1
            analysis = analyze_single_page_pdf(doc, entreprise, annee, args.review_dir)
 
        doc.close()
 
        results.append({
            "Entreprise": entreprise, "Annee": annee,
            "Pages_locales_originales": r.get("Pages_locales", ""),
            "Pages_candidat": r.get("Pages_candidat", ""),
            **analysis,
            "Titre_candidat": r.get("Titre_candidat", ""),
            "Fichier_candidat": r.get("Fichier_sortie", ""),
        })
 
        print(f"   [{analysis['verdict']:<16}] {entreprise} / {annee} ({n_pages} p.) - "
              f"{r.get('Titre_candidat', '')[:55]}")
 
    verdict_order = {
        "ERREUR_LECTURE": 0, "FICHIER_INTROUVABLE": 0,
        "SUSPECT_ANNONCE": 1, "A_VERIFIER": 2,
        "OK_AUTO": 3, "OK_MULTIPAGE": 4,
    }
    results.sort(key=lambda r: verdict_order.get(r["verdict"], 9))
 
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Entreprise", "Annee", "Pages_locales_originales", "Pages_candidat",
                  "verdict", "raisons", "n_chars", "n_tables_detected", "keywords_found",
                  "image_verification", "Titre_candidat", "Fichier_candidat"]
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
 
    n_multipage = sum(1 for r in results if r["verdict"] == "OK_MULTIPAGE")
    n_ok_auto = sum(1 for r in results if r["verdict"] == "OK_AUTO")
    n_annonce = sum(1 for r in results if r["verdict"] == "SUSPECT_ANNONCE")
    n_a_verifier = sum(1 for r in results if r["verdict"] == "A_VERIFIER")
    n_err = len(results) - n_multipage - n_ok_auto - n_annonce - n_a_verifier
 
    print("\n" + "=" * 90)
    print("RÉSUMÉ QUALITÉ")
    print(f"  PDF >1 page (confiance, non analysés)   : {n_multipage}")
    print(f"  PDF 1 page validés automatiquement (OK) : {n_ok_auto}")
    print(f"  PDF 1 page = communiqué vide (à exclure) : {n_annonce}")
    print(f"  PDF 1 page ambigus (image générée pour vérif) : {n_a_verifier}")
    print(f"  Erreurs / fichiers introuvables           : {n_err}")
    print(f"  -> CSV détaillé : {args.out.resolve()}")
    if n_a_verifier or n_annonce:
        print(f"  -> Images à vérifier visuellement dans : {args.review_dir.resolve()}")
    print("=" * 90)
 
 
if __name__ == "__main__":
    main()