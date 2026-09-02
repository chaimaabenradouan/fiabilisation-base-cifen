# 04_scrap_rapports_ammc.py — Scraper de rapports annuels sur le site AMMC

## Objectif

Télécharger, depuis le site de l'AMMC (`www.ammc.ma`, Autorité Marocaine du
Marché des Capitaux), les rapports annuels (états financiers) des
entreprises/années listées dans un fichier CSV d'entrée. Ce script constitue
une source alternative à la Bourse de Casablanca, utile pour compléter les
rapports introuvables sur `casablanca-bourse.com`.

## Fonctionnement du site AMMC (tel qu'exploité par le script)

1. **Liste des émetteurs**, paginée :
   `https://www.ammc.ma/fr/espace-emetteurs/liste-des-emetteurs?page=N`
   Contient un tableau "Dénomination" avec un lien vers la fiche de chaque
   émetteur.
2. **Fiche émetteur** (ex. AFMA) :
   `https://www.ammc.ma/fr/espace-emetteurs/liste-des-emetteurs/23894`
   Contient plusieurs blocs, dont un bloc "États financiers" : un tableau
   avec les colonnes "Année" et "Type rapport EF", lui-même paginé.
3. **Page de détail d'un rapport** (ex. AFMA - RFA 2020) :
   `https://www.ammc.ma/fr/espace-emetteurs/etats-financiers/afma-rfa-2020`
   Contient le lien direct vers le PDF ("Pièce jointe").

Le script chaîne ces trois niveaux : liste des émetteurs → fiche émetteur →
page de détail → PDF.

## Client HTTP (`ClientHTTP`)

Contrairement aux autres scripts du projet, celui-ci n'utilise **pas**
Playwright mais `requests` en HTTP simple (le site AMMC ne nécessite pas de
rendu JavaScript pour être scrapé).

- Session `requests` avec un `User-Agent` de navigateur standard.
- `get_soup(url)` : requête GET avec retries (`max_essais=3`, backoff
  linéaire `delai * essai`), parsing avec `BeautifulSoup` (parseur `lxml`),
  et **cache mémoire** (`_cache_soup`) pour ne jamais requêter deux fois la
  même URL dans une même exécution.
- `download(url, dest)` : téléchargement en streaming (`stream=True`,
  chunks de 64 Ko), avec les mêmes retries.

## Normalisation et rapprochement des noms d'entreprises

Le nom d'entreprise dans le CSV d'entrée ne correspond pas forcément
exactement à la dénomination utilisée par l'AMMC. Le script résout ce
problème par un matching flou :

### `normaliser(nom)`

- Remplace `_` et `-` par des espaces.
- Supprime les accents (normalisation Unicode NFKD → ASCII).
- Passe en majuscules, retire toute ponctuation.
- Retire les suffixes juridiques courants (`SA`, `S.A`, `SCA`, `SARL`,
  `GROUP`, `GROUPE`, `HOLDING`, `MAROC`, etc. — liste `SUFFIXES_A_IGNORER`).

### `similarite(a, b)`

Ratio de similarité `difflib.SequenceMatcher` entre deux chaînes déjà
normalisées.

### `trouver_meilleure_correspondance(nom_cherche, index_denominations, seuil)`

1. Normalise le nom cherché.
2. Pour chaque dénomination candidate de l'index AMMC :
   - normalise également ;
   - si les deux formes normalisées sont **identiques** → retour immédiat
     (meilleur cas) ;
   - sinon calcule la similarité, avec un **bonus** : si l'une des deux
     chaînes est incluse dans l'autre, le score est forcé à au moins 0.9 ;
   - garde le meilleur score rencontré.
3. Retourne la meilleure dénomination trouvée si son score dépasse `seuil`
   (paramétrable, défaut 0.55), sinon `None`.

## Étape 1 — Index des émetteurs (`construire_index_emetteurs`)

- Si un fichier de cache JSON existe déjà et que `--rafraichir-index` n'est
  pas demandé, charge directement l'index depuis le cache.
- Sinon, parcourt la liste paginée des émetteurs (`?page=N`) :
  - pour chaque page, cherche un `<table>` ; si aucun tableau n'est trouvé,
    la pagination est considérée terminée ;
  - pour chaque ligne contenant un lien vers `/liste-des-emetteurs/`, ajoute
    `{dénomination: url_fiche}` à l'index ;
  - continue tant qu'un lien `rel="next"` est présent, avec un garde-fou à 50
    pages.
- Sauvegarde l'index construit dans le fichier de cache JSON.

## Étape 2 — Tableau "États financiers" d'une fiche (paginé)

### `table_est_etats_financiers(table)`

Identifie le bon tableau parmi tous les `<table>` d'une page en vérifiant que
sa première ligne contient "année" (normalisé) et que le texte du tableau
contient "type rapport".

### `extraire_lignes_etats_financiers(table)`

Pour chaque ligne du tableau, extrait un tuple `(année, type_rapport,
url_detail)` à partir de la première cellule (année, retrouvée par regex sur
4 chiffres commençant par 19 ou 20) et du lien présent dans la dernière
cellule (type de rapport + URL de la page de détail).

### `recuperer_lignes_etats_financiers_paginees(client, url_fiche)`

Le tableau "États financiers" peut lui-même être paginé indépendamment du
reste de la fiche. Le script :

1. Charge la page de la fiche, identifie le tableau États financiers (la
   **dernière** table correspondante trouvée sur la page, au cas où il y en
   aurait plusieurs).
2. Extrait toutes ses lignes.
3. Cherche, **après** ce tableau dans le DOM (`find_all_next`), un lien
   `rel="next"` — pour ne suivre que la pagination propre à ce tableau et pas
   celle d'un autre bloc de la page.
4. Si un tel lien existe, recharge la page suivante et répète, avec une
   protection contre les boucles (`urls_visitees`).

## Étape 3 — Récupération de l'URL du PDF (`recuperer_url_pdf`)

Sur la page de détail d'un rapport, cherche le premier lien dont le `href` se
termine par `.pdf`.

## Programme principal (`main`)

1. Parse les arguments en ligne de commande (voir tableau ci-dessous).
2. Charge le CSV d'entrée (`charger_csv_manquants`) : liste de couples
   `(entreprise, annee)`.
3. Construit ou charge l'index des émetteurs AMMC.
4. Regroupe les demandes par entreprise (`par_entreprise`), pour ne charger la
   fiche de chaque entreprise qu'une seule fois même si plusieurs années sont
   demandées.
5. Pour chaque entreprise :
   1. Résout la dénomination AMMC correspondante (avec cache
      `cache_correspondance`) ; si aucune correspondance suffisante, toutes
      les années demandées pour cette entreprise sont marquées
      `entreprise_introuvable`.
   2. Récupère (avec cache `cache_lignes_ef`) toutes les lignes du tableau
      États financiers de la fiche trouvée.
   3. Pour chaque année demandée :
      - cherche une ligne exacte de type "Rapports annuels" pour cette année ;
      - à défaut, cherche une variante tolérante contenant "annuel" mais pas
        "semestre" ;
      - si toujours rien, statut `annee_introuvable` (avec le détail des
        types disponibles pour cette année, s'il y en a) ;
      - si un candidat est trouvé, vérifie si le fichier de destination
        existe déjà (`deja_present`), sinon récupère l'URL du PDF depuis la
        page de détail, télécharge (sauf en `--dry-run`, où l'action est
        seulement simulée et loguée), et enregistre le statut correspondant
        (`telecharge`, `pdf_introuvable`, ou `erreur`).
6. Écrit un rapport CSV récapitulatif avec une ligne par
   `(entreprise, annee)` traitée.
7. Affiche un résumé chiffré : nombre téléchargé / déjà présent / non résolu.

## Arguments CLI

| Argument | Défaut | Description |
|---|---|---|
| `--csv-manquants` | `annees_manquantes.csv` | CSV d'entrée, colonnes `entreprise,annee` |
| `--dossier-sortie` | `Rapports` | Dossier de destination des PDF |
| `--index-cache` | `ammc_index_emetteurs.json` | Fichier de cache de l'index des émetteurs |
| `--rapport-csv` | `rapport_scraping_ammc.csv` | CSV récapitulatif de l'exécution |
| `--delai` | 1.0 | Délai (s) entre deux requêtes HTTP |
| `--seuil-matching` | 0.55 | Seuil de similarité (0–1) pour le rapprochement des noms |
| `--rafraichir-index` | *(flag)* | Force la reconstruction de l'index des émetteurs |
| `--dry-run` | *(flag)* | N'effectue aucun téléchargement, affiche seulement les actions prévues |

## Statuts possibles dans le rapport de sortie

| Statut | Signification |
|---|---|
| `telecharge` | PDF téléchargé avec succès |
| `telecharge (simulation)` | Aurait été téléchargé (mode `--dry-run`) |
| `deja_present` | Le fichier existe déjà localement |
| `entreprise_introuvable` | Aucune fiche AMMC ne correspond au nom d'entreprise |
| `annee_introuvable` | L'entreprise est trouvée, mais pas de rapport annuel pour cette année |
| `pdf_introuvable` | La page de détail est trouvée, mais ne contient aucun lien PDF |
| `erreur` | Échec du téléchargement du PDF |

## Dépendances

- `requests`
- `beautifulsoup4` (parseur `lxml`)

## Fichiers produits

```
Rapports/<Entreprise>/<Annee>.pdf
ammc_index_emetteurs.json
rapport_scraping_ammc.csv
```
