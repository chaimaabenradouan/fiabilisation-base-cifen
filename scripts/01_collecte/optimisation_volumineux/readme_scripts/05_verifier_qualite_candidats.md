# Documentation — `05_verifier_qualite_candidats.py` (anciennement verify_candidates_quality.py)

## 1. Rôle dans le pipeline

Après que `smart_scrape_batch.py` ait téléchargé des candidats "plus légers" pour remplacer certains rapports volumineux, ce script vérifie que ces candidats sont **réellement fiables** (et pas, par exemple, un simple communiqué de presse d'une seule page renvoyant vers le site web au lieu du vrai rapport). Il ne modifie **rien** dans `Rapports/` ni dans les PDF eux-mêmes : il produit un CSV de verdicts + des images pour les cas ambigus.

## 2. Leçon apprise (v1 → v2)

La première version appliquait une heuristique texte (comptage de caractères/chiffres) à **tous** les PDF téléchargés. Cela générait de **faux suspects** sur des documents de plusieurs pages qui contenaient pourtant bien les tableaux Bilan/CPC (vérifié manuellement). Le script a donc été recentré : **seuls les PDF d'une seule page sont réellement ambigus** et méritent une analyse.

## 3. Logique de décision

| Cas | Verdict | Analyse effectuée |
|---|---|---|
| PDF de **plus d'une page** | `OK_MULTIPAGE` | Aucune — confiance directe (validé manuellement par l'utilisateur au préalable) |
| PDF **1 page**, signal texte fort | `OK_AUTO` | Détection de mots-clés financiers + au moins 1 tableau |
| PDF **1 page**, motif de communiqué explicite, aucun mot-clé financier | `SUSPECT_ANNONCE` | Génération d'une image PNG pour vérification |
| PDF **1 page**, signal faible/absent ou probable scan | `A_VERIFIER` | Génération d'une image PNG pour vérification |

## 4. Heuristiques utilisées (uniquement sur les PDF d'1 page)

### Mots-clés financiers (`FINANCIAL_KEYWORDS`)
Ex. : "bilan actif", "bilan passif", "total actif", "compte de produits et charges", "résultat net", "capitaux propres", "immobilisations"...

### Motifs de communiqué vide (`ANNOUNCEMENT_PATTERNS`)
Ex. : "disponible sur son site internet", "consultable sur le site", "veuillez consulter notre site"...

### Détection de tableaux
Utilise `page.find_tables()` de PyMuPDF pour compter le nombre de tableaux détectés sur la page.

### Règle de décision (`analyze_single_page_pdf`)
1. Si **≥ 1 tableau** ET **≥ 1 mot-clé financier** → `OK_AUTO` (signal fort et sans ambiguïté).
2. Sinon, si un motif de communiqué est détecté **et** aucun mot-clé financier → `SUSPECT_ANNONCE` (image générée pour confirmation visuelle).
3. Sinon (signal ambigu ou texte quasi vide, probable scan) → `A_VERIFIER` (image générée systématiquement).

Le texte est normalisé (accents supprimés, minuscules) avant comparaison pour être insensible à la casse et aux accents.

## 5. Génération d'images pour vérification visuelle

Pour tous les cas `SUSPECT_ANNONCE` et `A_VERIFIER`, la page est rendue en image PNG (résolution `RENDER_ZOOM = 2.5`) dans `smart_test_output/A_VERIFIER_VISUELLEMENT/<ENTREPRISE>_<ANNEE>.png`, afin que l'utilisateur puisse trancher **en un coup d'œil** sans avoir à ouvrir chaque PDF.

## 6. Entrée attendue

Le fichier `RECAP_GLOBAL.csv` produit par `smart_scrape_batch.py`. Seules les lignes avec `Statut == "candidat_telecharge"` (donc un fichier a bien été téléchargé) sont analysées.

## 7. Utilisation

```bash
python verify_candidates_quality.py --recap smart_test_output/RECAP_GLOBAL.csv
```

| Argument | Description | Défaut |
|---|---|---|
| `--recap` | Fichier récapitulatif produit par `smart_scrape_batch.py` | `smart_test_output/RECAP_GLOBAL.csv` |
| `--out` | Fichier CSV de sortie des verdicts | `smart_test_output/QUALITY_CHECK.csv` |
| `--review-dir` | Dossier des images générées pour vérification | `smart_test_output/A_VERIFIER_VISUELLEMENT` |

## 8. Sortie produite

**`smart_test_output/QUALITY_CHECK.csv`**, trié par ordre de priorité de vérification (erreurs et suspects en premier, cas fiables en dernier) :

| Colonne | Description |
|---|---|
| `Entreprise`, `Annee` | Identifiants |
| `Pages_locales_originales`, `Pages_candidat` | Comparaison des tailles |
| `verdict` | `OK_MULTIPAGE` / `OK_AUTO` / `SUSPECT_ANNONCE` / `A_VERIFIER` / `ERREUR_LECTURE` / `FICHIER_INTROUVABLE` |
| `raisons` | Explication textuelle du verdict |
| `n_chars`, `n_tables_detected`, `keywords_found` | Détail de l'analyse (uniquement pour les PDF 1 page) |
| `image_verification` | Chemin de l'image générée, le cas échéant |
| `Titre_candidat`, `Fichier_candidat` | Métadonnées du candidat |

Un résumé chiffré par catégorie de verdict est affiché en console.

## 9. Limites connues

- La confiance accordée automatiquement aux PDF `>1 page` (`OK_MULTIPAGE`) repose sur une vérification manuelle antérieure de l'utilisateur ; elle n'est pas garantie à 100 % pour de nouveaux cas jamais rencontrés.
- Les heuristiques (mots-clés, détection de tableaux) restent des approximations : un vrai rapport 1 page rédigé de façon inhabituelle pourrait être classé `A_VERIFIER` par excès de prudence — c'est un choix assumé (mieux vaut trop vérifier que rater une erreur).
- Ce script ne corrige rien automatiquement : c'est `generate_replacement_decisions.py` qui traduit ces verdicts en décisions concrètes.
