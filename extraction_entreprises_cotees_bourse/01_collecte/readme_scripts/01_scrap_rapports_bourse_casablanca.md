# 01_scrap_rapports_bourse_casablanca.py — Constitution de la base documentaire OMTPME

## Objectif

Construire la base documentaire brute des rapports financiers annuels des
entreprises cotées à la Bourse de Casablanca, en scrapant automatiquement le
site `casablanca-bourse.com` : liste des émetteurs, puis pour chaque émetteur
ses publications, puis téléchargement du meilleur rapport annuel disponible
pour chaque année.

## Configuration

| Paramètre | Valeur | Rôle |
|---|---|---|
| `BASE_URL` | `https://www.casablanca-bourse.com` | Domaine du site source |
| `LISTING_URL` | `.../fr/listing-des-emetteurs` | Page listant tous les émetteurs |
| `START_YEAR` | 2016 | Première année couverte |
| `CURRENT_YEAR` | 2026 | Dernière année couverte |
| `DATA_DIR` | `Rapports/` | Dossier de sortie des PDF, un sous-dossier par entreprise |
| `CSV_METADATA` | `rapports_metadata.csv` | Métadonnées de tous les rapports téléchargés |
| `CSV_EMETTEURS` | `liste_emetteurs.csv` | Liste des émetteurs avec leur URL de fiche |

Un logger écrit en parallèle dans la console et dans `phase2_scraping.log`.

## Scoring des documents (`DOCUMENT_SCORING`)

Chaque type de document possible est associé à un score de confiance, utilisé
pour choisir le meilleur document quand plusieurs sont disponibles pour la
même année :

| Type de document | Score |
|---|---|
| Rapport annuel | 100 |
| Rapport financier annuel | 98 |
| RFA | 95 |
| Document de référence | 92 |
| Comptes annuels | 90 |
| États financiers | 88 |
| États de synthèse | 85 |
| Rapport de gestion | 80 |
| Rapport consolidé | 75 |
| Annual report | 70 |
| Résultats annuels | 65 |

La fonction `score_document(title)` parcourt ce dictionnaire, cherche chaque
mot-clé (en minuscules) dans le titre du document, et retient le score le plus
élevé parmi les mots-clés trouvés.

## Déroulé du pipeline (`main`)

### Étape 1 — Récupération de tous les émetteurs (`get_all_issuers`)

1. Ouvre `LISTING_URL` avec Playwright (Chromium, `headless=False`, `slow_mo=400`).
2. Parcourt la table HTML de la page (`table tbody tr`), extrait pour chaque
   ligne : nom de l'entreprise, URL de sa fiche, ticker, capital, secteur.
3. Déduplique les entreprises déjà vues (`seen`, basé sur le nom).
4. Passe à la page suivante en cliquant sur le bouton de pagination
   correspondant, jusqu'à ce qu'aucun bouton suivant ne soit trouvé.
5. Sauvegarde le résultat dans `liste_emetteurs.csv` et retourne un
   `DataFrame` pandas.

### Étape 2 — Pour chaque émetteur

Pour chaque ligne du `DataFrame` d'émetteurs (boucle avec barre de progression
`tqdm`) :

1. Crée le sous-dossier `Rapports/<nom_nettoyé>/` (`clean_filename` retire les
   caractères interdits par le système de fichiers et tronque à 120 caractères).
2. **Ouverture des publications** (`open_publications_section`) : navigue vers
   la fiche de l'entreprise, clique sur l'onglet "Publications des émetteurs"
   (ou "Publications"), puis sur "Consulter".
3. **Collecte des documents** (`get_all_publication_pages`) : parcourt jusqu'à
   20 pages de résultats. Pour chaque lien PDF trouvé :
   - extrait le titre et l'URL ;
   - calcule son score via `score_document` ; **ignore le document si le
     score est inférieur à 60** ;
   - extrait l'année via une regex `20(\d{2})` sur le titre ; ignore le
     document si aucune année n'est trouvée ou si elle est hors de la plage
     `[START_YEAR, CURRENT_YEAR]`.
4. **Sélection du meilleur par année** (`select_best_per_year`) : pour chaque
   année, ne garde que le document au score le plus élevé.
5. **Téléchargement** (`download_pdf`) : télécharge chaque document retenu
   dans `Rapports/<entreprise>/<annee>.pdf` via une requête HTTP faite depuis
   le contexte Playwright (`page.request.get`). Si le fichier existe déjà
   localement, le téléchargement est sauté.
6. Pour chaque téléchargement réussi, enregistre une ligne de métadonnées
   (nom, ticker, capital, secteur, année, titre, URL, chemin local, date de
   scraping, score de confiance, type détecté).

### Étape 3 — Sauvegarde finale

Toutes les métadonnées collectées sont assemblées dans un `DataFrame` et
écrites dans `rapports_metadata.csv`.

## Gestion des erreurs

- Chaque entreprise est traitée dans un bloc `try/except` : une erreur sur une
  entreprise (fiche introuvable, timeout, etc.) est loguée et n'interrompt pas
  le traitement des entreprises suivantes.
- Le navigateur Playwright est fermé dans un bloc `finally`, garantissant sa
  fermeture même en cas d'erreur fatale.

## Dépendances

- `playwright` (synchrone, navigateur Chromium visible)
- `beautifulsoup4`
- `pandas`
- `tqdm`

## Fichiers produits

```
Rapports/
└── <Entreprise>/
    └── <Annee>.pdf
liste_emetteurs.csv
rapports_metadata.csv
phase2_scraping.log
```
