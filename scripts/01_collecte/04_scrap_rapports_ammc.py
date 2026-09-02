#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrap_rapports_ammc.py

Télécharge automatiquement, depuis le site de l'AMMC (www.ammc.ma), les
"Rapports annuels" (états financiers) des entreprises/années listées dans
un fichier CSV d'entrée (colonnes: entreprise, annee).

FONCTIONNEMENT DU SITE (tel qu'observé) :

1) Liste des émetteurs (paginée) :
   https://www.ammc.ma/fr/espace-emetteurs/liste-des-emetteurs?page=N
   -> Contient un tableau "Dénomination" avec un lien vers la fiche de
      chaque émetteur, ex: /fr/espace-emetteurs/liste-des-emetteurs/23894

2) Fiche émetteur (ex: AFMA) :
   https://www.ammc.ma/fr/espace-emetteurs/liste-des-emetteurs/23894
   -> Contient plusieurs blocs (Caractéristiques, Opérations financières,
      Communiqués de presse, Franchissement de seuil, États financiers...).
      Le bloc "États financiers" est un tableau avec les colonnes
      "Année" et "Type rapport EF", CE TABLEAU EST LUI-MÊME PAGINÉ.
      On y cherche les lignes "Rapports annuels" pour l'année voulue.

3) Page de détail du rapport (ex: AFMA - RFA 2020) :
   https://www.ammc.ma/fr/espace-emetteurs/etats-financiers/afma-rfa-2020
   -> Contient le lien direct vers le PDF ("Pièce jointe").

Le script :
  a) Construit (et met en cache) un index {dénomination -> URL fiche émetteur}
     en parcourant TOUTES les pages de la liste des émetteurs.
  b) Fait correspondre chaque "entreprise" du CSV d'entrée à une fiche AMMC
     (matching tolérant : accents, tirets/underscores, suffixes SA/SCA...).
  c) Pour chaque entreprise résolue, parcourt (avec pagination) le tableau
     "États financiers" de sa fiche, cherche la ligne "Rapports annuels"
     de l'année demandée.
  d) Suit le lien vers la page de détail, en extrait le PDF, et le
     télécharge dans : <dossier_sortie>/<entreprise>/<annee>.pdf
  e) Écrit un rapport CSV récapitulatif (téléchargé / introuvable / etc.)

Dépendances :
    pip install requests beautifulsoup4 lxml --break-system-packages

Usage basique :
    python scrap_rapports_ammc.py --csv-manquants annees_manquantes.csv --dossier-sortie Rapports

Options utiles :
    --dry-run              Ne télécharge rien, affiche seulement ce qui serait fait.
    --delai 1.5             Délai (s) entre deux requêtes HTTP (défaut: 1.0).
    --rafraichir-index      Force la reconstruction de l'index des émetteurs.
    --seuil-matching 0.55   Seuil de similarité pour le rapprochement de noms (0-1).
"""

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ammc.ma"
LISTE_EMETTEURS_URL = f"{BASE_URL}/fr/espace-emetteurs/liste-des-emetteurs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

SUFFIXES_A_IGNORER = [
    "S.A", "SA", "S.C.A", "SCA", "S.A.R.L", "SARL", "GROUP", "GROUPE",
    "COMPANY", "CO", "HOLDING", "MAROC", "-",
]


# --------------------------------------------------------------------------
# Utilitaires réseau
# --------------------------------------------------------------------------

class ClientHTTP:
    """Petit wrapper autour de requests avec délai, retries et cache mémoire."""

    def __init__(self, delai: float = 1.0, timeout: int = 30, max_essais: int = 3):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delai = delai
        self.timeout = timeout
        self.max_essais = max_essais
        self._cache_soup: dict[str, BeautifulSoup] = {}

    def get_soup(self, url: str) -> Optional[BeautifulSoup]:
        if url in self._cache_soup:
            return self._cache_soup[url]
        for essai in range(1, self.max_essais + 1):
            try:
                time.sleep(self.delai)
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "lxml")
                self._cache_soup[url] = soup
                return soup
            except requests.RequestException as e:
                print(f"    ! Erreur réseau ({essai}/{self.max_essais}) sur {url} : {e}")
                time.sleep(self.delai * essai)
        return None

    def download(self, url: str, dest: Path) -> bool:
        for essai in range(1, self.max_essais + 1):
            try:
                time.sleep(self.delai)
                resp = self.session.get(url, timeout=self.timeout, stream=True)
                resp.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                return True
            except requests.RequestException as e:
                print(f"    ! Erreur de téléchargement ({essai}/{self.max_essais}) sur {url} : {e}")
                time.sleep(self.delai * essai)
        return False


# --------------------------------------------------------------------------
# Normalisation / matching des noms d'entreprises
# --------------------------------------------------------------------------

def normaliser(nom: str) -> str:
    """Met un nom en forme canonique pour comparaison (majuscule, sans accents,
    sans ponctuation, sans suffixes juridiques courants)."""
    nom = nom.replace("_", " ").replace("-", " ")
    nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    nom = nom.upper()
    nom = re.sub(r"[^A-Z0-9 ]", " ", nom)
    mots = nom.split()
    mots = [m for m in mots if m not in SUFFIXES_A_IGNORER]
    return " ".join(mots).strip()


def similarite(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def trouver_meilleure_correspondance(
    nom_cherche: str, index_denominations: list[str], seuil: float
) -> Optional[str]:
    """Retourne la dénomination AMMC la plus proche de `nom_cherche`, ou None."""
    cible = normaliser(nom_cherche)
    if not cible:
        return None

    meilleure, meilleur_score = None, 0.0
    for denom in index_denominations:
        cand = normaliser(denom)
        if not cand:
            continue
        # correspondance exacte après normalisation -> gagne direct
        if cand == cible:
            return denom
        # inclusion (l'un contient l'autre) -> bon indice
        score = similarite(cible, cand)
        if cible in cand or cand in cible:
            score = max(score, 0.9)
        if score > meilleur_score:
            meilleure, meilleur_score = denom, score

    if meilleur_score >= seuil:
        return meilleure
    return None


# --------------------------------------------------------------------------
# Étape 1 : construire l'index des émetteurs (dénomination -> URL fiche)
# --------------------------------------------------------------------------

def construire_index_emetteurs(client: ClientHTTP, cache_path: Path, forcer: bool) -> dict[str, str]:
    if cache_path.exists() and not forcer:
        print(f"Index émetteurs chargé depuis le cache : {cache_path}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    print("Construction de l'index des émetteurs AMMC (peut prendre quelques minutes)...")
    index: dict[str, str] = {}

    page = 0
    while True:
        url = LISTE_EMETTEURS_URL if page == 0 else f"{LISTE_EMETTEURS_URL}?page={page}"
        soup = client.get_soup(url)
        if soup is None:
            print(f"  ! Impossible de charger la page {page}, arrêt de la pagination.")
            break

        table = soup.find("table")
        if table is None:
            print(f"  Page {page} : aucun tableau trouvé, fin de la pagination.")
            break

        lignes_trouvees = 0
        for tr in table.find_all("tr"):
            lien = tr.find("a", href=True)
            if lien and "/liste-des-emetteurs/" in lien["href"]:
                denom = lien.get_text(strip=True)
                href = urljoin(BASE_URL, lien["href"])
                if denom:
                    index[denom] = href
                    lignes_trouvees += 1

        print(f"  Page {page} : {lignes_trouvees} émetteur(s) trouvé(s). Total cumulé : {len(index)}")

        if lignes_trouvees == 0:
            break

        # Cherche un lien de pagination "page suivante" (rel=next) pour savoir s'il faut continuer
        lien_suivant = soup.find("a", attrs={"rel": "next"})
        if not lien_suivant:
            break
        page += 1

        if page > 50:  # garde-fou anti boucle infinie
            print("  ! Plus de 50 pages parcourues, arrêt de sécurité.")
            break

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"Index construit : {len(index)} émetteur(s). Sauvegardé dans {cache_path}\n")
    return index


# --------------------------------------------------------------------------
# Étape 2 : lire le tableau "États financiers" (paginé) d'une fiche émetteur
# --------------------------------------------------------------------------

def table_est_etats_financiers(table) -> bool:
    """Détecte le bon tableau en cherchant les en-têtes 'Année' et 'Type rapport'."""
    entete_texte = table.get_text(" ", strip=True).lower()
    premiere_ligne = table.find("tr")
    if premiere_ligne is None:
        return False
    texte_ligne1 = premiere_ligne.get_text(" ", strip=True).lower()
    return "annee" in normaliser(texte_ligne1).lower() or (
        "année" in texte_ligne1 and "type rapport" in entete_texte
    )


def extraire_lignes_etats_financiers(table) -> list[tuple[str, str, str]]:
    """Retourne une liste de tuples (annee, type_rapport, url_detail)."""
    resultats = []
    for tr in table.find_all("tr"):
        cellules = tr.find_all("td")
        if len(cellules) < 2:
            continue
        annee_texte = cellules[0].get_text(strip=True) if len(cellules) >= 2 else ""
        cell_type = cellules[-1]
        lien = cell_type.find("a", href=True)
        if not lien:
            continue
        annee_match = re.search(r"\b(19|20)\d{2}\b", annee_texte) or re.search(
            r"\b(19|20)\d{2}\b", tr.get_text(" ", strip=True)
        )
        if not annee_match:
            continue
        annee = annee_match.group(0)
        type_rapport = lien.get_text(strip=True)
        url_detail = urljoin(BASE_URL, lien["href"])
        resultats.append((annee, type_rapport, url_detail))
    return resultats


def recuperer_lignes_etats_financiers_paginees(
    client: ClientHTTP, url_fiche: str
) -> list[tuple[str, str, str]]:
    """Parcourt la fiche émetteur et, si le tableau États financiers est paginé,
    suit sa pagination spécifique (lien rel=next situé après ce tableau)."""
    toutes_lignes: list[tuple[str, str, str]] = []
    url_courante = url_fiche
    urls_visitees = set()

    while url_courante and url_courante not in urls_visitees:
        urls_visitees.add(url_courante)
        soup = client.get_soup(url_courante)
        if soup is None:
            break

        table_ef = None
        for table in soup.find_all("table"):
            if table_est_etats_financiers(table):
                table_ef = table  # on garde la DERNIÈRE table correspondante trouvée sur la page
        if table_ef is None:
            break

        toutes_lignes.extend(extraire_lignes_etats_financiers(table_ef))

        # Cherche le lien "page suivante" (rel=next) qui apparaît APRÈS ce tableau
        # dans le document (pour ne pas suivre la pagination d'un autre bloc).
        lien_suivant = None
        for candidat in table_ef.find_all_next("a", attrs={"rel": "next"}):
            lien_suivant = candidat
            break

        if lien_suivant and lien_suivant.get("href"):
            url_courante = urljoin(BASE_URL, lien_suivant["href"])
        else:
            url_courante = None

    return toutes_lignes


# --------------------------------------------------------------------------
# Étape 3 : depuis la page de détail du rapport, récupérer l'URL du PDF
# --------------------------------------------------------------------------

def recuperer_url_pdf(client: ClientHTTP, url_detail: str) -> Optional[str]:
    soup = client.get_soup(url_detail)
    if soup is None:
        return None
    for lien in soup.find_all("a", href=True):
        if lien["href"].lower().endswith(".pdf"):
            return urljoin(BASE_URL, lien["href"])
    return None


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------

@dataclass
class LigneResultat:
    entreprise: str
    annee: str
    statut: str  # telecharge | deja_present | annee_introuvable | entreprise_introuvable | pdf_introuvable | erreur
    detail: str = ""
    chemin_fichier: str = ""


def charger_csv_manquants(path: Path) -> list[tuple[str, str]]:
    lignes = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entreprise = (row.get("entreprise") or "").strip()
            annee = (row.get("annee") or "").strip()
            if entreprise and annee:
                lignes.append((entreprise, annee))
    return lignes


def main():
    parser = argparse.ArgumentParser(description="Scraper AMMC : télécharge les rapports annuels manquants.")
    parser.add_argument("--csv-manquants", default="annees_manquantes.csv",
                         help="CSV d'entrée avec colonnes 'entreprise,annee' (défaut: annees_manquantes.csv)")
    parser.add_argument("--dossier-sortie", default="Rapports",
                         help="Dossier où stocker les PDF téléchargés (défaut: Rapports)")
    parser.add_argument("--index-cache", default="ammc_index_emetteurs.json",
                         help="Fichier de cache de l'index des émetteurs (défaut: ammc_index_emetteurs.json)")
    parser.add_argument("--rapport-csv", default="rapport_scraping_ammc.csv",
                         help="CSV récapitulatif de l'exécution (défaut: rapport_scraping_ammc.csv)")
    parser.add_argument("--delai", type=float, default=1.0, help="Délai en secondes entre requêtes (défaut: 1.0)")
    parser.add_argument("--seuil-matching", type=float, default=0.55,
                         help="Seuil de similarité (0-1) pour rapprocher les noms d'entreprises (défaut: 0.55)")
    parser.add_argument("--rafraichir-index", action="store_true",
                         help="Force la reconstruction de l'index des émetteurs (ignore le cache)")
    parser.add_argument("--dry-run", action="store_true",
                         help="N'effectue aucun téléchargement, affiche seulement ce qui serait fait")
    args = parser.parse_args()

    csv_manquants = Path(args.csv_manquants)
    dossier_sortie = Path(args.dossier_sortie)
    index_cache = Path(args.index_cache)
    rapport_csv = Path(args.rapport_csv)

    if not csv_manquants.is_file():
        print(f"Erreur : le fichier '{csv_manquants}' n'existe pas.")
        sys.exit(1)

    demandes = charger_csv_manquants(csv_manquants)
    if not demandes:
        print("Aucune ligne (entreprise, annee) trouvée dans le CSV d'entrée.")
        sys.exit(0)

    print(f"{len(demandes)} demande(s) (entreprise, année) à traiter.\n")

    client = ClientHTTP(delai=args.delai)

    index_emetteurs = construire_index_emetteurs(client, index_cache, args.rafraichir_index)
    denominations = list(index_emetteurs.keys())

    # Regroupe les demandes par entreprise pour ne charger chaque fiche émetteur qu'une fois
    par_entreprise: dict[str, list[str]] = {}
    for entreprise, annee in demandes:
        par_entreprise.setdefault(entreprise, []).append(annee)

    resultats: list[LigneResultat] = []
    cache_correspondance: dict[str, Optional[str]] = {}
    cache_lignes_ef: dict[str, list[tuple[str, str, str]]] = {}

    for entreprise, annees in par_entreprise.items():
        print(f"Entreprise : {entreprise}  (années demandées : {', '.join(annees)})")

        # 1) Trouver la fiche AMMC correspondante
        if entreprise not in cache_correspondance:
            cache_correspondance[entreprise] = trouver_meilleure_correspondance(
                entreprise, denominations, args.seuil_matching
            )
        denom_trouvee = cache_correspondance[entreprise]

        if not denom_trouvee:
            print(f"  ✗ Aucune fiche AMMC correspondante trouvée pour '{entreprise}'.")
            for annee in annees:
                resultats.append(LigneResultat(entreprise, annee, "entreprise_introuvable"))
            print()
            continue

        url_fiche = index_emetteurs[denom_trouvee]
        print(f"  -> Correspond à '{denom_trouvee}' sur AMMC : {url_fiche}")

        # 2) Récupérer (avec cache) toutes les lignes du tableau États financiers
        if url_fiche not in cache_lignes_ef:
            cache_lignes_ef[url_fiche] = recuperer_lignes_etats_financiers_paginees(client, url_fiche)
        lignes_ef = cache_lignes_ef[url_fiche]

        if not lignes_ef:
            print("  ! Aucune ligne 'États financiers' trouvée sur cette fiche.")

        # 3) Pour chaque année demandée, chercher la ligne "Rapports annuels"
        for annee in annees:
            candidats = [
                (a, t, u) for (a, t, u) in lignes_ef
                if a == annee and t.strip().lower() == "rapports annuels"
            ]
            if not candidats:
                # on tente une variante tolérante (ex: "Rapports consolidés annuels")
                candidats = [
                    (a, t, u) for (a, t, u) in lignes_ef
                    if a == annee and "annuel" in t.lower() and "semestre" not in t.lower()
                ]

            if not candidats:
                types_dispo = sorted({t for (a, t, u) in lignes_ef if a == annee})
                detail = f"types disponibles pour {annee} : {types_dispo}" if types_dispo else "année absente du tableau"
                print(f"  ✗ {annee} : rapport annuel introuvable ({detail}).")
                resultats.append(LigneResultat(entreprise, annee, "annee_introuvable", detail))
                continue

            annee_trouvee, type_trouve, url_detail = candidats[0]
            dest_pdf = dossier_sortie / entreprise / f"{annee}.pdf"

            if dest_pdf.exists():
                print(f"  = {annee} : déjà présent ({dest_pdf}), ignoré.")
                resultats.append(LigneResultat(entreprise, annee, "deja_present", "", str(dest_pdf)))
                continue

            url_pdf = recuperer_url_pdf(client, url_detail)
            if not url_pdf:
                print(f"  ✗ {annee} : page de détail trouvée mais aucun PDF dedans ({url_detail}).")
                resultats.append(LigneResultat(entreprise, annee, "pdf_introuvable", url_detail))
                continue

            if args.dry_run:
                print(f"  [DRY-RUN] {annee} : téléchargerait {url_pdf} -> {dest_pdf}")
                resultats.append(LigneResultat(entreprise, annee, "telecharge (simulation)", url_pdf, str(dest_pdf)))
                continue

            ok = client.download(url_pdf, dest_pdf)
            if ok:
                print(f"  ✓ {annee} : téléchargé -> {dest_pdf}")
                resultats.append(LigneResultat(entreprise, annee, "telecharge", url_pdf, str(dest_pdf)))
            else:
                print(f"  ✗ {annee} : échec du téléchargement depuis {url_pdf}")
                resultats.append(LigneResultat(entreprise, annee, "erreur", url_pdf))

        print()

    # Écriture du rapport récapitulatif
    with open(rapport_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["entreprise", "annee", "statut", "detail", "chemin_fichier"])
        for r in resultats:
            writer.writerow([r.entreprise, r.annee, r.statut, r.detail, r.chemin_fichier])

    nb_ok = sum(1 for r in resultats if r.statut.startswith("telecharge"))
    nb_deja = sum(1 for r in resultats if r.statut == "deja_present")
    nb_echec = len(resultats) - nb_ok - nb_deja

    print("=" * 60)
    print(f"Terminé : {nb_ok} téléchargé(s), {nb_deja} déjà présent(s), {nb_echec} non résolu(s)/échec(s).")
    print(f"Rapport détaillé : {rapport_csv}")


if __name__ == "__main__":
    main()