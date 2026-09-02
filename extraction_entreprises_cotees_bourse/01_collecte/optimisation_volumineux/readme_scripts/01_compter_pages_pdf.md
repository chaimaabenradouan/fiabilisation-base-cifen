# Documentation — `01_compter_pages_pdf.py` (anciennement count_pdf_pages.py)

## 1. Rôle dans le pipeline

C'est le **tout premier script** exécuté dans la chaîne d'optimisation des rapports : il parcourt le dossier local `Rapports/` (déjà rempli avec les PDF téléchargés au préalable) et compte le nombre de pages de chaque document, afin de produire une base de données structurée servant à toutes les étapes suivantes (notamment la détection des rapports "volumineux").

## 2. Structure de dossier attendue

```
Rapports/
├── Entreprise_A/
│   ├── 2018.pdf
│   ├── 2019.pdf
│   └── 2020.pdf
├── Entreprise_B/
└── ...
```

Chaque sous-dossier de `Rapports/` correspond à une entreprise, et chaque fichier PDF à l'intérieur est nommé selon l'année du rapport (ex. `2018.pdf`).

## 3. Fonctionnement étape par étape

1. **Parcours du dossier `Rapports/`** (`scan_reports_folder`) : pour chaque sous-dossier (= entreprise), parcours de tous les fichiers `.pdf` qu'il contient.
2. **Comptage des pages** (`count_pages_in_pdf`) via la bibliothèque `pypdf`. En cas d'erreur de lecture (fichier corrompu, protégé...), la page compte `-1` et un message d'erreur est affiché, sans interrompre le traitement des autres fichiers.
3. **Extraction de l'année** à partir du nom de fichier (sans l'extension `.pdf`), utilisée comme clé dans le dictionnaire de résultats.
4. **Sauvegarde des résultats** dans deux formats complémentaires (JSON détaillé + CSV résumé).

## 4. Utilisation

```bash
python count_pdf_pages.py
```

Aucun argument en ligne de commande n'est prévu ; le dossier source est fixé à `Rapports` dans le code (`scan_reports_folder("Rapports")`).

**Dépendance requise** : `pypdf` (`pip install pypdf`) — le script vérifie sa présence au démarrage et s'arrête proprement avec un message clair si elle est absente.

## 5. Sorties produites

### `rapport_pages.json`
Structure imbriquée par entreprise puis par année :

```json
{
  "Entreprise_A": {
    "2018": {"file": "2018.pdf", "pages": 45, "full_path": "Rapports/Entreprise_A/2018.pdf"},
    "2019": {"file": "2019.pdf", "pages": 52, "full_path": "..."}
  }
}
```

### `rapport_pages.csv`
Version "plate" équivalente, séparateur `;`, colonnes : `entreprise`, `annee`, `pages`, `fichier`.

Un résumé (✅/❌ par fichier traité, avec le nombre de pages) est affiché en console au fur et à mesure du traitement.

## 6. Rôle en amont de la suite du pipeline

Le fichier `rapport_pages.json` produit ici est l'**entrée directe** de `detect_volumineux_from_json.py`, qui l'utilise pour identifier les rapports dépassant un certain seuil de pages, eux-mêmes traités ensuite par `smart_scrape_batch.py`.

## 7. Limites connues

- Le script suppose que le nom du fichier PDF (sans extension) correspond exactement à l'année du rapport ; toute autre convention de nommage fausserait l'extraction de l'année.
- Un PDF illisible (page compte `-1`) reste néanmoins inclus dans le JSON/CSV de sortie avec cette valeur négative — il faut donc filtrer ces cas en aval si nécessaire (le script suivant, `detect_volumineux_from_json.py`, ne fait pas ce filtrage explicitement).
- Aucune vérification n'est faite sur le contenu réel du PDF (juste le nombre de pages) : ce script ne dit rien sur la qualité ou la pertinence du document.
