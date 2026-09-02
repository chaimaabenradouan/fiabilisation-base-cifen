# 03_rescrap_pages_uniques_fausses.py — Re-scraping avec vérification de contenu (v2)

**Étape 3 / 3** du pipeline de nettoyage des rapports 1 page.
Emplacement dans le projet : `01_collecte/nettoyage_pages_uniques/03_rescrap_pages_uniques_fausses.py`

## Objectif

Pour chaque `(Entreprise, Année)` marqué `FAKE_ANNONCE`, `SCANNE_A_VERIFIER` ou
`A_VERIFIER` à l'étape 2, retourne sur le site de la Bourse de Casablanca et
retélécharge **tous** les documents disponibles pour cette année, analyse leur
**contenu réel**, puis choisit — parmi ceux confirmés réels — le PDF le plus léger
(le moins de pages) pour remplacer le faux.

 **Ne touche jamais à `Rapports/`.** Toutes les sorties vont dans `nettoyage_1page/`.
Le remplacement effectif du PDF dans `Rapports/` reste une étape manuelle,
après vérification des CSV de comparaison.

## Correctifs par rapport à la v1

| Problème v1 | Correctif v2 |
|---|---|
| Filtrait les candidats par leur **titre** (`DOCUMENT_SCORING`), ratant les documents au titre atypique (ex. "Avis de convocation à l'AGO" contenant en fait les comptes annuels) | Collecte **tous** les documents de l'année sans filtre de titre : le **contenu** décide |
| Excluait systématiquement tout candidat d'1 page | Analyse le contenu réel de **chaque** candidat (tableaux + mots-clés CGNC) et choisit le minimum de pages **parmi ceux confirmés réels**, qu'ils fassent 1 page ou 300 |

## Utilisation

```bash
python 03_rescrap_pages_uniques_fausses.py \
    --classification RESCRAPE_TARGETS.csv \
    --verdicts FAKE_ANNONCE SCANNE_A_VERIFIER A_VERIFIER
```

### Arguments

| Argument | Défaut | Description |
|---|---|---|
| `--classification` | *(requis)* | CSV produit par l'étape 2 (ou un sous-ensemble filtré) |
| `--emetteurs-csv` | `liste_emetteurs.csv` | CSV de correspondance nom d'entreprise → URL de sa fiche sur casablanca-bourse.com |
| `--verdicts` | `["FAKE_ANNONCE"]` | Liste des verdicts à traiter (peut inclure plusieurs valeurs) |

## Déroulé du script

1. Charge le CSV de classification, filtre les lignes dont le `verdict` est dans `--verdicts`.
2. Ouvre un navigateur **Playwright (Chromium, non headless, slow_mo=250ms)**.
3. Pour chaque `(Entreprise, Année)` :
   1. Cherche l'URL de la fiche entreprise (`find_company_url`) via correspondance exacte, puis floue (inclusion de sous-chaîne) sur le nom normalisé.
   2. Ouvre la section "Publications des émetteurs" de la fiche (`open_publications_section`).
   3. Parcourt toutes les pages de résultats (jusqu'à 30) et collecte **tous** les liens PDF dont l'année extraite du titre correspond à l'année cible (`collect_documents_for_year`) — sans aucun filtre de titre.
   4. Pour chaque document candidat : télécharge le PDF, l'analyse (`analyze_pdf_bytes`), en déduit un verdict `OK_REEL` / `FAKE_ANNONCE` / `A_VERIFIER`.
   5. Sauvegarde un CSV de comparaison de **tous** les candidats avec leur verdict : `nettoyage_1page/<ENTREPRISE>/comparaison_<ENTREPRISE>_<ANNEE>.csv`.
   6. Parmi les candidats `OK_REEL`, retient celui avec le **moins de pages** (`min(..., key=nb_pages)`).
   7. Télécharge ce meilleur candidat dans `nettoyage_1page/<ENTREPRISE>/<ANNEE>_candidat_leger.pdf`.
4. Ferme le navigateur, écrit le rapport global `nettoyage_1page/RESCRAPE_REPORT.csv`.

## Analyse de contenu (`analyze_pdf_bytes`)

Reprend les mêmes règles que `02_classifier_qualite_page_unique.py`, avec une
nuance pour les documents longs :

- Le comptage de tableaux (`find_tables()`) n'est effectué que si le document a
  **≤ 15 pages** (`MAX_PAGES_FOR_TABLE_CHECK`), pour des raisons de performance.
- Verdict `FAKE_ANNONCE` : motif de communiqué détecté ET 0 catégorie trouvée.
- Verdict `OK_REEL` : ≥ 2 catégories trouvées (bilan actif/passif/CPC) ET (document long **ou** ≥ 1 tableau détecté).
- Sinon : `A_VERIFIER`.

## Statuts possibles dans le rapport final

| Statut | Signification |
|---|---|
| `CANDIDAT_TROUVE` | Un candidat réel plus léger a été trouvé et téléchargé |
| `AUCUN_CANDIDAT_FIABLE` | Des documents existent en ligne mais aucun n'a été confirmé réel |
| `AUCUN_DOCUMENT_EN_LIGNE` | Aucun document trouvé pour cette année sur le site |
| `URL_INTROUVABLE` | L'entreprise n'a pas pu être associée à une URL de fiche |
| `ERREUR_SCRAPING` | Erreur lors de la navigation / collecte des documents |
| `ECHEC_TELECHARGEMENT` | Le meilleur candidat n'a pas pu être téléchargé |

## Fichiers de sortie

```
nettoyage_1page/
├── <ENTREPRISE>/
│   ├── comparaison_<ENTREPRISE>_<ANNEE>.csv   # tous les candidats + verdict qualité
│   └── <ANNEE>_candidat_leger.pdf              # meilleur candidat réel (si trouvé)
└── RESCRAPE_REPORT.csv                         # résumé global par (Entreprise, Année)
```

### Structure de `comparaison_<ENTREPRISE>_<ANNEE>.csv`

| Colonne | Description |
|---|---|
| `Titre` | Titre du document tel qu'affiché sur le site |
| `Nb_pages` | Nombre de pages du PDF |
| `Verdict` | `OK_REEL` / `FAKE_ANNONCE` / `A_VERIFIER` |
| `Detail` | Détail du score |
| `Categories_trouvees` | Catégories CGNC détectées |
| `Taille_Ko` | Taille du fichier |
| `Erreur` | Message d'erreur éventuel (téléchargement) |
| `URL_PDF` | URL source du PDF |

## Dépendances

- `PyMuPDF` (`fitz`)
- `beautifulsoup4` (`bs4`)
- `playwright` (mode synchrone, navigateur Chromium)
- Module maison `moteur_reconnaissance_comptable_cgnc.py`

## Points d'attention

- Le navigateur est lancé en **mode visible** (`headless=False`) avec un
  `slow_mo=250` — utile pour observer/déboguer, mais plus lent en exécution batch.
- Aucune automatisation du remplacement dans `Rapports/` : les CSV de comparaison
  doivent être relus avant tout remplacement manuel.
