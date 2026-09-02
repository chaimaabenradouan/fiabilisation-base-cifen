# Documentation — `03_scrap_candidats_legers_bourse.py` (anciennement smart_scrape_batch.py)

## 1. Rôle dans le pipeline

Ce script est le **cœur du processus d'optimisation des rapports**. Pour chaque rapport annuel jugé "volumineux" (typiquement identifié en amont par `count_pdf_pages.py` + `detect_volumineux_from_json.py`), il cherche en ligne, sur le site de la Bourse de Casablanca, une **version plus légère du même document** (moins de pages), et la télécharge dans un dossier séparé pour vérification — **sans jamais modifier les fichiers originaux**.

## 2. Principe de sécurité fondamental

> **Ne modifie JAMAIS `Rapports/`. Tout sort dans `smart_test_output/<ENTREPRISE>/`, prêt à être vérifié manuellement avant remplacement.**

C'est la règle structurante de tout le pipeline aval : ce script (et ceux qui le suivent) séparent strictement la **détection/proposition** de candidats du **remplacement effectif**, qui n'est fait que par `apply_replacements.py`, avec sauvegarde systématique des originaux.

## 3. Entrée attendue

Un fichier JSON (`rapports_volumineux.json`, généré par `detect_volumineux_from_json.py`) de la forme :

```json
{
  "rapports_volumineux": {
    "MANAGEM": [{"annee": "2018", "pages": 330, "fichier": "2018.pdf"}, ...],
    ...
  }
}
```

## 4. Fonctionnement étape par étape

Pour chaque entreprise du JSON :

1. **Résolution de l'URL** de sa fiche émetteur via `liste_emetteurs.csv` (`find_company_url`), avec une correspondance par nom normalisé (accents, casse, ponctuation supprimés) et, en repli, une correspondance partielle (l'un contient l'autre).
2. **Ouverture de la section "Publications"** de la fiche entreprise (`open_publications_section`), en cliquant sur "Publications des émetteurs" puis "Consulter".
3. **Scraping de TOUTES les publications en une seule passe** (`collect_all_documents_for_company`) : toutes les pages de résultats sont parcourues (avec la même logique de pagination robuste que `generate_emetteurs.py`, gérant aussi les `...`), et chaque document PDF trouvé est scoré selon son titre (`score_document`) pour déterminer son type probable (rapport annuel, RFA, comptes annuels, etc.) et son année (`extract_year`).
4. **Pour chaque année demandée** dans le JSON pour cette entreprise :
   - Comptage du nombre de pages du PDF **local** déjà présent dans `Rapports/`.
   - Récupération du nombre de pages de chaque candidat **en ligne** de la même année (téléchargement temporaire + comptage via PyMuPDF).
   - Sauvegarde d'un CSV de comparaison (`comparaison_<ENTREPRISE>_<ANNEE>.csv`) listant tous les candidats (local + en ligne) avec leurs métadonnées.
   - Sélection du candidat avec le **moins de pages** parmi ceux valides.
   - Si le meilleur candidat est le fichier local lui-même → statut `deja_optimal`, rien n'est téléchargé.
   - Sinon → téléchargement du candidat dans `smart_test_output/<ENTREPRISE>/<ANNEE>_candidat_leger.pdf`, statut `candidat_telecharge`.

## 5. Système de score des documents

Chaque titre de document est comparé (insensible à la casse) à un dictionnaire de mots-clés avec un score associé (`DOCUMENT_SCORING`), par exemple :

| Mot-clé détecté | Score |
|---|---|
| "rapport annuel" | 100 |
| "rapport financier annuel" | 98 |
| "document de référence" | 92 |
| "états financiers" | 88 |
| "rapport de gestion" | 80 |
| "annual report" | 70 |

Seuls les documents avec un score `>= DEFAULT_MIN_SCORE` (60 par défaut, ajustable via `--seuil-score`) sont considérés comme candidats valides.

## 6. Reprise automatique après interruption

Un **registre de progression** (`smart_test_output/batch_progress.json`) enregistre chaque job `Entreprise/Année` déjà traité. En cas de relance après une interruption (crash, coupure réseau...), les jobs déjà marqués `done` sont **ignorés automatiquement**, sauf si `--force` est utilisé pour tout retraiter.

## 7. Un seul navigateur pour tout le batch

Contrairement à une approche naïve qui ouvrirait un navigateur par entreprise, ce script utilise **une seule instance Playwright pour tout le batch**, ce qui réduit fortement le temps d'exécution total sur un grand nombre d'entreprises.

## 8. Utilisation

```bash
# Traitement complet
python smart_scrape_batch.py --json rapports_volumineux.json

# Test sur les 3 premières entreprises
python smart_scrape_batch.py --json rapports_volumineux.json --limit 3

# Test sur une entreprise précise
python smart_scrape_batch.py --json rapports_volumineux.json --entreprise MANAGEM

# Reprise automatique après interruption (comportement par défaut)
python smart_scrape_batch.py --json rapports_volumineux.json

# Forcer le retraitement complet (ignore le registre de reprise)
python smart_scrape_batch.py --json rapports_volumineux.json --force
```

| Argument | Description | Défaut |
|---|---|---|
| `--json` | Chemin du JSON des rapports volumineux (obligatoire) | — |
| `--rapports-dir` | Dossier contenant les PDF originaux | `Rapports` |
| `--emetteurs-csv` | Fichier de correspondance entreprise → URL | `liste_emetteurs.csv` |
| `--seuil-score` | Score minimum pour qu'un document en ligne soit considéré | `60` |
| `--entreprise` | Ne traiter qu'une seule entreprise (test) | Aucun |
| `--limit` | Limiter aux N premières entreprises (test) | Aucun |
| `--force` | Ignorer le registre de reprise et tout retraiter | `False` |

## 9. Sorties produites

| Fichier | Contenu |
|---|---|
| `smart_test_output/<ENTREPRISE>/<ANNEE>_candidat_leger.pdf` | Le meilleur candidat trouvé en ligne, si plus léger que l'original |
| `smart_test_output/<ENTREPRISE>/comparaison_<ENTREPRISE>_<ANNEE>.csv` | Détail de tous les candidats comparés (local + en ligne) |
| `smart_test_output/RECAP_GLOBAL.csv` | **À consulter en premier** : synthèse de tous les jobs traités |
| `smart_test_output/batch_progress.json` | Registre de reprise |
| `smart_scrape_batch.log` | Journal complet de l'exécution |

Le fichier `RECAP_GLOBAL.csv` contient, pour chaque (Entreprise, Année) : le nombre de pages avant/après, le gain de pages, le statut (`deja_optimal` / `candidat_telecharge` / `erreur` / `non_trouve`), le titre du candidat retenu et son chemin de fichier.

## 10. Limites connues

- Le critère de sélection du "meilleur" candidat est **uniquement le nombre de pages le plus faible** — un candidat très léger mais de mauvaise qualité (ex. communiqué au lieu du vrai rapport) peut être sélectionné à tort. C'est précisément ce que corrige `verify_candidates_quality.py` en aval.
- La résolution du nom d'entreprise vers son URL dépend de la qualité du fichier `liste_emetteurs.csv` ; toute entreprise absente de ce fichier est automatiquement ignorée (`non_trouve`).
- Le score de document est basé sur des mots-clés dans le titre uniquement ; un titre mal formé ou non standard peut fausser la sélection.
