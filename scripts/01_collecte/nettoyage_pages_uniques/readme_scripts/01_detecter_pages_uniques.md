# 01_detecter_pages_uniques.py — Détection des PDF d'une seule page

**Étape 1 / 3** du pipeline de nettoyage des rapports 1 page.
Emplacement dans le projet : `01_collecte/nettoyage_pages_uniques/01_detecter_pages_uniques.py`

## Objectif

Scanner **tout** le dossier `Rapports/` (toutes entreprises, toutes années) et repérer
les PDF qui ne font **qu'une seule page**. C'est cette catégorie précise qui s'est
révélée trompeuse dans le pipeline global :

- parfois un **vrai état financier condensé** (à garder tel quel),
- parfois un simple **communiqué** renvoyant vers le site web de l'entreprise pour
  consulter le vrai rapport (à re-scraper).

Ce script ne fait **aucun jugement de contenu** : il se contente de détecter le
nombre de pages. Le tri qualité arrive à l'étape 2.

## Garanties

- **Lecture seule** : ne modifie jamais rien dans `Rapports/`.
- Idempotent : peut être relancé autant de fois que nécessaire, régénère juste le CSV de sortie.

## Utilisation

```bash
python 01_detecter_pages_uniques.py --rapports-dir Rapports
```

### Arguments

| Argument | Défaut | Description |
|---|---|---|
| `--rapports-dir` | `Rapports` | Dossier racine contenant les sous-dossiers `<ENTREPRISE>/<ANNEE>.pdf` |
| `--out` | `nettoyage_1page/ONEPAGE_REPORTS.csv` | Chemin du CSV de sortie |

## Fonctionnement interne

1. Récupère tous les fichiers via le glob `*/*.pdf` (un sous-dossier par entreprise, un PDF par année).
2. Pour chaque PDF, ouvre le document avec **PyMuPDF (`fitz`)** et lit `doc.page_count`.
3. Si `n_pages == 1` : enregistre l'entrée (entreprise, année, chemin, taille en Ko).
4. Si l'ouverture échoue (PDF corrompu, illisible...) : incrémente un compteur d'erreurs et passe au suivant, sans interrompre le scan.
5. Écrit le résultat dans un CSV (encodage `utf-8-sig` pour compatibilité Excel).
6. Affiche un résumé : nombre total de PDF scannés, nombre de PDF 1 page trouvés, nombre d'erreurs.

## Structure du CSV de sortie (`ONEPAGE_REPORTS.csv`)

| Colonne | Description |
|---|---|
| `Entreprise` | Nom du dossier entreprise (= nom du sous-dossier dans `Rapports/`) |
| `Annee` | Nom du fichier sans extension (ex. `2019`) |
| `Chemin` | Chemin complet vers le PDF |
| `Taille_Ko` | Taille du fichier en kilooctets |

## Dépendances

- `PyMuPDF` (`fitz`)

## Prochaine étape

➡️ `02_classifier_qualite_page_unique.py` — classifie chaque PDF 1 page comme
`OK_REEL`, `FAKE_ANNONCE`, `SCANNE_A_VERIFIER` ou `A_VERIFIER`.
