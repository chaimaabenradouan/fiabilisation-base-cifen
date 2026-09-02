#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rescue_excluded_candidates.py
=========================================================================
HYPOTHÈSE : pour les entreprises/années exclues (Action="garder_original"
avec Verdict_automatique = A_VERIFIER ou SUSPECT_ANNONCE dans
REPLACEMENT_DECISIONS.csv), smart_scrape_batch.py a peut-être choisi un
faux communiqué d'1 page simplement parce qu'il avait le MOINS de pages,
en ignorant un AUTRE candidat valide (4, 5 pages...) trouvé la même
année mais écarté uniquement parce qu'il n'était pas le plus léger.

Ce script NE RE-SCRAPE PAS le site. Il relit les fichiers
comparaison_<ENTREPRISE>_<ANNEE>.csv déjà générés par smart_scrape_batch.py
(qui contiennent TOUS les candidats vus pour cette année, pas juste le
gagnant), et cherche s'il existe un candidat "En ligne" avec nb_pages > 1
qu'on a laissé de côté. Comme tu l'as toi-même vérifié : tout PDF >1 page
s'est révélé fiable jusqu'ici -> on peut lui faire confiance directement.

Si un tel candidat existe, il est téléchargé (c'est la SEULE requête
réseau de ce script - juste le fichier, pas un re-scraping complet) et
ajouté automatiquement dans overrides.csv avec Action=remplacer.

Usage :
    python rescue_excluded_candidates.py --decisions smart_test_output/REPLACEMENT_DECISIONS.csv

Sorties :
    smart_test_output/<ENTREPRISE>/<ANNEE>_candidat_alternatif.pdf   (si trouvé)
    smart_test_output/RESCUE_REPORT.csv
    overrides.csv mis à jour automatiquement (nouvelles lignes ajoutées,
    les lignes existantes ne sont jamais modifiées)
=========================================================================
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_DECISIONS = Path("smart_test_output/REPLACEMENT_DECISIONS.csv")
DEFAULT_OVERRIDES = Path("overrides.csv")
DEFAULT_RESCUE_REPORT = Path("smart_test_output/RESCUE_REPORT.csv")
OUTPUT_DIR = Path("smart_test_output")


def setup_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False, slow_mo=250)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    page = context.new_page()
    return playwright, browser, page


def find_excluded_candidates(decisions_path: Path) -> list[dict]:
    """Les lignes qu'on a exclues à cause d'un verdict A_VERIFIER/SUSPECT_ANNONCE
    (on ignore les exclusions par override manuel explicite, ex: JET_CONTRACTORS,
    qui ont déjà été vérifiées et confirmées fausses sans alternative)."""
    with open(decisions_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    excluded = []
    for r in rows:
        if r["Action"].strip().lower() != "garder_original":
            continue
        if r["Raison"].startswith("OVERRIDE MANUEL"):
            continue  # déjà tranché manuellement, pas la peine de re-chercher
        if r["Verdict_automatique"] in ("A_VERIFIER", "SUSPECT_ANNONCE"):
            excluded.append(r)
    return excluded


def find_alternative_in_comparison_csv(entreprise: str, annee: str, current_fake_path: str) -> dict | None:
    """Cherche dans comparaison_<ENTREPRISE>_<ANNEE>.csv un candidat 'En ligne'
    avec nb_pages > 1, différent du candidat déjà retenu (le faux)."""
    comp_path = OUTPUT_DIR / entreprise / f"comparaison_{entreprise}_{annee}.csv"
    if not comp_path.exists():
        return None

    with open(comp_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    candidates = []
    for r in rows:
        if r["Source"] != "En ligne":
            continue
        try:
            n_pages = int(r["Nb_pages"])
        except (ValueError, TypeError):
            continue
        if n_pages <= 1:
            continue  # on ne veut QUE des candidats >1 page (règle de confiance)
        candidates.append({**r, "Nb_pages": n_pages})

    if not candidates:
        return None

    # Le plus léger parmi les fiables (>1 page)
    candidates.sort(key=lambda c: c["Nb_pages"])
    return candidates[0]


def download_alternative(page, url: str, dest: Path) -> bool:
    try:
        response = page.request.get(url, timeout=60000, ignore_https_errors=True)
        if response.status == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.body())
            return True
    except Exception as exc:
        print(f"   ❌ Échec téléchargement {url} : {exc}")
    return False


def append_to_overrides(overrides_path: Path, entreprise: str, annee: str,
                          fichier_candidat: str, titre: str, n_pages: int) -> None:
    file_exists = overrides_path.exists()
    fieldnames = ["Entreprise", "Annee", "Action", "Raison", "Fichier_candidat_override", "Pages_candidat_override"]

    existing_rows = []
    if file_exists:
        with open(overrides_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for r in reader:
                r.setdefault("Fichier_candidat_override", "")
                r.setdefault("Pages_candidat_override", "")
                existing_rows.append(r)

    existing_rows.append({
        "Entreprise": entreprise,
        "Annee": annee,
        "Action": "remplacer",
        "Raison": f"RESCUE AUTO : alternative >1 page trouvée dans les candidats déjà scrapés "
                   f"('{titre}', {n_pages} pages), le candidat 1 page initial était un faux",
        "Fichier_candidat_override": fichier_candidat,
        "Pages_candidat_override": n_pages,
    })

    with open(overrides_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)


def main():
    parser = argparse.ArgumentParser(description="Cherche des alternatives fiables pour les candidats exclus.")
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--report", type=Path, default=DEFAULT_RESCUE_REPORT)
    args = parser.parse_args()

    if not args.decisions.exists():
        print(f"❌ Fichier introuvable : {args.decisions}")
        return

    excluded = find_excluded_candidates(args.decisions)
    print(f"🔍 {len(excluded)} entreprise(s)/année(s) exclue(s) à examiner...\n")

    results = []
    found_alternatives = []

    for row in excluded:
        entreprise, annee = row["Entreprise"], row["Annee"]
        alt = find_alternative_in_comparison_csv(entreprise, annee, row["Fichier_candidat"])

        if alt:
            print(f"   ✅ [{entreprise} / {annee}] Alternative trouvée : "
                  f"'{alt['Titre'][:60]}' ({alt['Nb_pages']} pages)")
            results.append({
                "Entreprise": entreprise, "Annee": annee, "Statut": "ALTERNATIVE_TROUVEE",
                "Titre_alternative": alt["Titre"], "Pages_alternative": alt["Nb_pages"],
                "URL": alt["URL_PDF"],
            })
            found_alternatives.append((entreprise, annee, alt))
        else:
            print(f"   — [{entreprise} / {annee}] Aucune alternative >1 page trouvée "
                  f"(le PDF original reste le meilleur choix)")
            results.append({
                "Entreprise": entreprise, "Annee": annee, "Statut": "AUCUNE_ALTERNATIVE",
                "Titre_alternative": "", "Pages_alternative": "", "URL": "",
            })

    if found_alternatives:
        print(f"\n📥 Téléchargement de {len(found_alternatives)} alternative(s)...")
        playwright, browser, page = setup_browser()
        try:
            for entreprise, annee, alt in found_alternatives:
                dest = OUTPUT_DIR / entreprise / f"{annee}_candidat_alternatif.pdf"
                ok = download_alternative(page, alt["URL_PDF"], dest)
                if ok:
                    append_to_overrides(args.overrides, entreprise, annee,
                                         str(dest), alt["Titre"], alt["Nb_pages"])
                    print(f"   ✅ Téléchargé et ajouté à overrides.csv : {dest}")
                else:
                    print(f"   ❌ Échec du téléchargement pour {entreprise}/{annee}")
                time.sleep(1)
        finally:
            browser.close()
            playwright.stop()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with open(args.report, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["Entreprise", "Annee", "Statut", "Titre_alternative",
                                                 "Pages_alternative", "URL"])
        writer.writeheader()
        writer.writerows(results)

    n_found = sum(1 for r in results if r["Statut"] == "ALTERNATIVE_TROUVEE")
    print("\n" + "=" * 90)
    print(f"RÉSUMÉ : {n_found} alternative(s) trouvée(s) sur {len(excluded)} exclusion(s) examinées.")
    print(f"Rapport : {args.report.resolve()}")
    if n_found:
        print(f"overrides.csv mis à jour -> relance generate_replacement_decisions.py pour les intégrer.")
    print("=" * 90)


if __name__ == "__main__":
    main()