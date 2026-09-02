#!/usr/bin/env python3
"""
Automatisation complète SANS clé API : Nom d'entreprise -> URL welipro.com -> ICE/RC/IF

Utilise DuckDuckGo (via la librairie 'duckduckgo-search') pour trouver la
fiche welipro.com de chaque société, sans avoir besoin de créer de compte
ni de clé API.

------------------------------------------------------------------
INSTALLATION :
    pip install duckduckgo-search requests beautifulsoup4

USAGE :
    python auto_extract_ddg.py entreprises.csv resultats.csv

Le CSV d'entrée doit avoir une colonne "Nom_Entreprise".
------------------------------------------------------------------
"""

import csv
import re
import sys
import time
import random
import difflib
import unicodedata

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS  # nouveau nom du package
except ImportError:
    try:
        from duckduckgo_search import DDGS  # ancien nom, au cas où
    except ImportError:
        print("ERREUR: aucune librairie de recherche DuckDuckGo installée.")
        print("Installe-la avec: pip install ddgs")
        sys.exit(1)

DEBUG = True  # passe à False une fois que ça marche, pour un affichage plus court

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Délais entre requêtes - à ne pas descendre trop bas pour éviter de se faire
# bloquer par DuckDuckGo ou de surcharger welipro.com
SEARCH_MIN_DELAY = 3.0
SEARCH_MAX_DELAY = 6.0
FETCH_MIN_DELAY = 2.0
FETCH_MAX_DELAY = 4.0


SIMILARITY_THRESHOLD = 0.90  # très strict: on préfère "NON TROUVÉ" à une mauvaise donnée


def normalize_name(name: str) -> str:
    """Normalise un nom de société pour comparaison: minuscules, sans accents,
    sans ponctuation, mots vides juridiques retirés (mais rien de plus)."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    # ne retire que des mots ENTIERS (pas des sous-chaînes), pour éviter de
    # tronquer des mots comme "sarl" à l'intérieur d'un autre mot
    stopwords = {"sa", "s", "a", "sarl", "sca", "groupe", "group", "ste",
                 "societe", "société", "maroc"}
    # ATTENTION: on retire "maroc" seulement si le nom a plus d'un mot
    # significatif, sinon "TAQA MOROCCO" vs "TAQA" perdrait tout son sens
    words = [w for w in name.split() if w]
    return " ".join(words)


def names_match(query_name: str, page_name: str) -> bool:
    """Vérifie que le nom trouvé sur la page correspond BIEN à la société
    recherchée. Volontairement strict: mieux vaut rater une correspondance
    valide que d'accepter une société différente (ex: 'Wafa Assurance' ne
    doit jamais matcher 'AGL Assurances')."""
    a = normalize_name(query_name)
    b = normalize_name(page_name)
    if not a or not b:
        return False

    a_words = set(a.split())
    b_words = set(b.split())

    # Règle 1: tous les mots significatifs (>=3 lettres) de la requête
    # doivent se retrouver dans le nom de la page (ou l'inverse pour les
    # sigles courts comme "AGMA", "CFG").
    a_sig = {w for w in a_words if len(w) >= 3}
    b_sig = {w for w in b_words if len(w) >= 3}
    if not a_sig or not b_sig:
        return False

    missing_from_page = a_sig - b_sig
    coverage = 1 - (len(missing_from_page) / len(a_sig))

    if DEBUG:
        print(f"         [check] '{a}' vs '{b}' -> couverture={coverage:.2f} "
              f"(mots requête: {sorted(a_sig)}, mots page: {sorted(b_sig)})")

    # Le critère de couverture (tous les mots significatifs de la requête
    # doivent se retrouver dans le nom de la page) suffit à lui seul à
    # bloquer les vrais faux positifs (ex: "wafa assurance" ne couvre pas
    # "agl assurances" -> coverage=0.5 -> rejeté), sans casser les cas
    # simples comme "AFMA SA" vs juste "AFMA" (coverage=1.0, accepté).
    return coverage >= 0.9


def get_page_title(soup: BeautifulSoup) -> str:
    """Récupère le nom de la société tel qu'affiché sur la fiche welipro
    (le titre h1, généralement '# Nom de la société')."""
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    if soup.title:
        return soup.title.get_text(strip=True)
    return ""


def _search_once(query: str, max_results: int = 8):
    """Fait une recherche DDG et retourne la liste brute de résultats."""
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results, region="ma-fr"))


def find_and_verify_welipro_page(nom_entreprise: str, retries: int = 3):
    """Cherche sur DuckDuckGo la fiche welipro.com d'une société, VÉRIFIE
    que le nom affiché sur chaque page candidate correspond réellement à la
    société recherchée (pour éviter les faux positifs comme confondre
    'BANQUE CENTRALE POPULAIRE' avec 'Banque Populaire Patrimoine II'),
    et retourne (url, html) de la première fiche qui matche, ou (None, None)."""

    queries = [
        f'site:maroc.welipro.com {nom_entreprise}',
        f'"{nom_entreprise}" welipro ICE RC IF Maroc',
        f'{nom_entreprise} maroc.welipro.com ICE',
    ]

    candidats_rejetes = []

    for query in queries:
        for attempt in range(1, retries + 1):
            try:
                results = _search_once(query)
                if DEBUG:
                    print(f"   requête: {query!r} -> {len(results)} résultat(s)")

                for r in results:
                    link = r.get("href") or r.get("link") or ""
                    if "welipro.com" not in link or "/c/" not in link:
                        continue

                    # On va vérifier le nom réel affiché sur la page avant
                    # d'accepter quoi que ce soit
                    try:
                        time.sleep(random.uniform(FETCH_MIN_DELAY, FETCH_MAX_DELAY))
                        html = fetch(link)
                        soup = BeautifulSoup(html, "html.parser")
                        page_name = get_page_title(soup)
                    except Exception as e:
                        if DEBUG:
                            print(f"      (échec de vérification pour {link}: {e})")
                        continue

                    if names_match(nom_entreprise, page_name):
                        if DEBUG:
                            print(f"      -> MATCH accepté: '{page_name}' ({link})")
                        return link, html
                    else:
                        candidats_rejetes.append((link, page_name))
                        if DEBUG:
                            print(f"      -> rejeté (nom différent): "
                                  f"'{page_name}' ne correspond pas à "
                                  f"'{nom_entreprise}'")

                break  # cette requête a été traitée (avec ou sans succès), on
                       # passe à la requête suivante si rien n'a matché
            except Exception as e:
                wait = attempt * 5
                print(f"   (recherche échouée, tentative {attempt}/{retries}, "
                      f"nouvelle tentative dans {wait}s: {e})")
                time.sleep(wait)

    if DEBUG and candidats_rejetes:
        print(f"   Aucun candidat validé. Rejetés: {candidats_rejetes[:3]}")

    return None, None


FIELD_LABELS = [
    ("ICE", "(ICE)"),
    ("RC", "(RC)"),
    ("IF", "(IF)"),
    ("Capital", "Capital"),
    ("Forme_juridique", "Forme juridique"),
    ("Date_creation", "Date de création"),
]


def _get_block(text: str, label: str, all_labels: list) -> str:
    """Retourne le texte compris entre `label` et le prochain label connu
    (ou la fin d'un bloc raisonnable), pour isoler proprement la valeur
    associée à ce champ sur la page."""
    idx = text.find(label)
    if idx == -1:
        return ""
    start = idx + len(label)
    # cherche le prochain label (parmi tous les labels connus) après start
    next_positions = []
    for _, other_label in all_labels:
        if other_label == label:
            continue
        pos = text.find(other_label, start)
        if pos != -1:
            next_positions.append(pos)
    end = min(next_positions) if next_positions else start + 200
    return text[start:end]


def extract_fields(html: str) -> dict:
    """Extrait ICE, RC, IF, Capital, Forme juridique, Date de création à
    partir du HTML d'une fiche welipro.com, en isolant le bloc de texte
    propre à chaque champ (plus fiable qu'une seule grosse regex globale)."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    result = {
        "ICE": "", "RC": "", "IF": "", "Capital": "",
        "Forme_juridique": "", "Date_creation": "",
    }

    # ICE : suite de 9 à 20 chiffres
    ice_block = _get_block(text, "(ICE)", FIELD_LABELS)
    ice_match = re.search(r"([0-9]{9,20})", ice_block)
    if ice_match:
        result["ICE"] = ice_match.group(1).strip()

    # RC : numéro + ville entre parenthèses si présente -> "NUMERO (VILLE)"
    rc_block = _get_block(text, "(RC)", FIELD_LABELS)
    rc_num_match = re.search(r"([0-9]{1,9})", rc_block)
    rc_ville_match = re.search(r"\(?\s*([A-ZÉÈÀÂÎÔÛÇ][A-ZÉÈÀÂÎÔÛÇ\- ]{2,30})\s*\)?", rc_block)
    if rc_num_match:
        rc_num = rc_num_match.group(1).strip()
        rc_ville = rc_ville_match.group(1).strip().rstrip(")").lstrip("(") if rc_ville_match else ""
        # évite de confondre un mot générique capturé par erreur avec une vraie ville
        if rc_ville and len(rc_ville) >= 3:
            result["RC"] = f"{rc_num} ({rc_ville})"
        else:
            result["RC"] = rc_num

    # IF : suite de chiffres (3 à 15)
    if_block = _get_block(text, "(IF)", FIELD_LABELS)
    if_match = re.search(r"([0-9]{3,15})", if_block)
    if if_match:
        result["IF"] = if_match.group(1).strip()

    # Capital : chiffres + devise (MAD, DHS...)
    capital_block = _get_block(text, "Capital", FIELD_LABELS)
    capital_match = re.search(r"([0-9][0-9\s]*[0-9])\s*([A-Z]{3})", capital_block)
    if capital_match:
        result["Capital"] = f"{capital_match.group(1).strip()} {capital_match.group(2)}"

    # Forme juridique : texte libre, on prend le premier segment avant un
    # éventuel prochain label ou retour à la ligne parasite
    forme_block = _get_block(text, "Forme juridique", FIELD_LABELS)
    forme_clean = forme_block.strip().lstrip(":").strip()
    if forme_clean:
        result["Forme_juridique"] = forme_clean.split("\n")[0].strip()

    # Date de création : format JJ/MM/AAAA
    date_block = _get_block(text, "Date de création", FIELD_LABELS)
    date_match = re.search(r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", date_block)
    if date_match:
        result["Date_creation"] = date_match.group(1).strip()

    return result


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def main():
    if len(sys.argv) != 3:
        print("Usage: python auto_extract_ddg.py <entreprises.csv> <resultats.csv>")
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]

    with open(input_path, newline="", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in)
        rows = list(reader)

    if not rows or "Nom_Entreprise" not in rows[0]:
        print("ERREUR: le CSV d'entrée doit contenir une colonne 'Nom_Entreprise'")
        sys.exit(1)

    fieldnames = [
        "Nom_Entreprise", "ICE", "RC", "IF", "Capital", "Forme_juridique",
        "Date_creation", "Source", "URL_Source", "Statut",
    ]

    # Reprise possible: si le fichier de sortie existe déjà partiellement,
    # on ne refait pas les entreprises déjà traitées.
    deja_traitees = set()
    file_exists = False
    try:
        with open(output_path, newline="", encoding="utf-8") as f_existing:
            for r in csv.DictReader(f_existing):
                deja_traitees.add(r["Nom_Entreprise"])
        file_exists = True
    except FileNotFoundError:
        pass

    mode = "a" if file_exists else "w"
    with open(output_path, mode, newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for i, row in enumerate(rows, 1):
            nom = row["Nom_Entreprise"].strip()

            if nom in deja_traitees:
                print(f"[{i}/{len(rows)}] {nom}: déjà traité, ignoré")
                continue

            out_row = {
                "Nom_Entreprise": nom, "ICE": "", "RC": "", "IF": "",
                "Capital": "", "Forme_juridique": "", "Date_creation": "",
                "Source": "Welipro.com (base légale, non-officielle)",
                "URL_Source": "", "Statut": "NON TROUVÉ",
            }

            try:
                url, html = find_and_verify_welipro_page(nom)
                out_row["URL_Source"] = url or ""

                if not url:
                    print(f"[{i}/{len(rows)}] {nom}: aucune fiche vérifiée trouvée")
                    writer.writerow(out_row)
                    f_out.flush()
                    time.sleep(random.uniform(SEARCH_MIN_DELAY, SEARCH_MAX_DELAY))
                    continue

                data = extract_fields(html)
                out_row.update(data)
                if data["ICE"] or data["RC"] or data["IF"]:
                    out_row["Statut"] = "TROUVÉ"

                print(f"[{i}/{len(rows)}] {nom}: "
                      f"ICE={data['ICE'] or '-'} RC={data['RC'] or '-'} "
                      f"IF={data['IF'] or '-'} -> {out_row['Statut']}")

            except Exception as e:
                print(f"[{i}/{len(rows)}] {nom}: ERREUR ({e})")

            writer.writerow(out_row)
            f_out.flush()
            time.sleep(random.uniform(SEARCH_MIN_DELAY, SEARCH_MAX_DELAY))

    print(f"\nTerminé. Résultats écrits dans: {output_path}")


if __name__ == "__main__":
    main()