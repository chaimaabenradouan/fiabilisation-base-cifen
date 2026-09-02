# 02_diagnostic_completude_rapports_bourse.py — Analyse des années manquantes (système de fichiers)

## Objectif

Établir un état des lieux complet de la base documentaire en se basant
uniquement sur le **système de fichiers réel** du dossier `Rapports/` (et non
sur un fichier de métadonnées qui pourrait être désynchronisé). Pour chaque
entreprise, détermine quelles années (2016 à 2025) possèdent un rapport PDF et
lesquelles manquent, puis produit un CSV de suivi trié par priorité.

Le dossier `Rapports/` fait ici office de **source de vérité unique** :
c'est la présence réelle d'un fichier `<annee>.pdf` dans un sous-dossier
d'entreprise qui détermine si un rapport est considéré comme disponible.

## Configuration

| Paramètre | Valeur | Rôle |
|---|---|---|
| `PROJECT_ROOT` | `Path(__file__).resolve().parent.parent` | Racine du projet (2 niveaux au-dessus du script) |
| `ROOT_DIR` | `PROJECT_ROOT / "Rapports"` | Dossier scanné |
| `OUTPUT_CSV` | `PROJECT_ROOT / "annees_manquantes.csv"` | CSV de sortie |
| `EXPECTED_YEARS` | `range(2016, 2026)` | Années attendues, soit 2016 à 2025 inclus (10 ans) |

Si `Rapports/` n'existe pas, le script lève immédiatement une
`FileNotFoundError` plutôt que de produire un résultat vide silencieusement.

## Parcours du dossier

Pour chaque sous-dossier direct de `Rapports/` (un sous-dossier = une
entreprise) :

1. Le nom de l'entreprise est dérivé du nom du dossier, avec les underscores
   remplacés par des espaces (`company_dir.name.replace("_", " ")`).
2. Recherche **récursive** de tous les fichiers `.pdf` dans ce dossier
   (`glob("**/*.pdf")`).
3. Pour chaque PDF trouvé, le nom de fichier (sans extension) est interprété
   comme une année (`int(pdf_file.stem.strip())`).
   - Si la conversion échoue (le nom de fichier n'est pas un entier, par
     exemple un fichier nommé autrement) → le fichier est ignoré silencieusement.
   - Si l'année convertie n'est pas dans `EXPECTED_YEARS` → elle n'est pas
     comptabilisée.
4. Les années valides sont accumulées par entreprise dans
   `company_data: dict[str, list[int]]`.

## Calcul des années manquantes

Pour chaque entreprise :

1. `years_present` : ensemble trié et dédupliqué des années trouvées.
2. `missing_years` : toutes les années de `EXPECTED_YEARS` qui ne sont pas
   dans `years_present`.
3. Construction d'une ligne de résultat :
   - `Nom` : nom de l'entreprise ;
   - `Nb_Rapports` : nombre d'années présentes ;
   - `Nb_Annees_Manquantes` : nombre d'années manquantes ;
   - `Annees_Manquantes` : liste des années manquantes, sous forme de chaîne
     séparée par des virgules (ex. `"2016, 2017, 2021"`).

## Tri et écriture du CSV

Le `DataFrame` résultat est trié par :

1. `Nb_Annees_Manquantes` décroissant (les entreprises les plus incomplètes
   en premier),
2. puis `Nom` croissant (ordre alphabétique en cas d'égalité).

### `save_csv_with_fallback(df, output_path)`

Écriture sécurisée du CSV, pensée pour un environnement où le fichier
pourrait être ouvert ailleurs (Excel, par exemple) au moment de l'écriture :

1. Écrit d'abord dans un fichier temporaire `<output>.tmp`.
2. Remplace ensuite le fichier final par ce temporaire (`Path.replace`),
   opération atomique qui évite un CSV partiellement écrit.
3. En cas de `PermissionError` (fichier verrouillé), écrit à la place dans un
   fichier horodaté (`annees_manquantes_<YYYYMMDD_HHMMSS>.csv`) et avertit
   l'utilisateur, plutôt que d'échouer complètement.

Cette fonction retourne le chemin réellement utilisé, qui remplace la
variable `OUTPUT_CSV` initiale.

## Résumé affiché en console

À la fin de l'exécution, le script affiche :

- le nombre total d'entreprises analysées ;
- le nombre total de rapports trouvés (somme de `Nb_Rapports`) ;
- le nombre total d'années manquantes (somme de `Nb_Annees_Manquantes`) ;
- l'entreprise la **plus complète** (dernière ligne du tri, donc la moins
  d'années manquantes) avec son ratio `Nb_Rapports/10` ;
- l'entreprise la **moins complète** (première ligne du tri) avec son ratio.

## Structure du CSV de sortie (`annees_manquantes.csv`)

| Colonne | Description |
|---|---|
| `Nom` | Nom de l'entreprise (nom du dossier, underscores remplacés par des espaces) |
| `Nb_Rapports` | Nombre d'années pour lesquelles un PDF a été trouvé (sur 10 attendues) |
| `Nb_Annees_Manquantes` | Nombre d'années manquantes (sur 10) |
| `Annees_Manquantes` | Liste des années manquantes séparées par des virgules (vide si complet) |

Ce fichier constitue l'entrée directe de `fill_missing_reports_v5.py`, qui
filtre les entreprises avec `Nb_Annees_Manquantes > 0` pour cibler le
rattrapage.

## Dépendances

- `pandas`

## Fichier produit

```
annees_manquantes.csv
```
