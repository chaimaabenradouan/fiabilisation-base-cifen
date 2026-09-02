# Documentation — `07_recuperer_candidats_exclus.py` (anciennement rescue_excluded_candidates.py)

## 1. Rôle dans le pipeline

Ce script tente de **récupérer automatiquement** des cas exclus à tort. Son hypothèse de départ : pour certaines entreprises/années exclues (verdict `A_VERIFIER` ou `SUSPECT_ANNONCE`), `smart_scrape_batch.py` a pu choisir un faux communiqué d'1 page **simplement parce que c'était le candidat avec le moins de pages**, en ignorant un autre candidat valide (4, 5 pages...) trouvé la même année mais écarté uniquement parce qu'il n'était pas le plus léger.

## 2. Principe : pas de nouveau scraping du site

Point important : ce script **ne re-scrape pas** le site de la Bourse de Casablanca. Il relit simplement les fichiers `comparaison_<ENTREPRISE>_<ANNEE>.csv` **déjà générés** par `smart_scrape_batch.py`, qui contiennent la liste de **tous** les candidats vus cette année-là (pas seulement le gagnant). La seule requête réseau effectuée est le **téléchargement** du candidat alternatif s'il en existe un.

## 3. Règle de confiance appliquée

Comme observé empiriquement (vérifié manuellement par l'utilisateur) : **tout PDF de plus d'une page s'est révélé fiable jusqu'ici**. Le script cherche donc, parmi les candidats "En ligne" du CSV de comparaison, celui avec `nb_pages > 1` et le moins de pages parmi ceux-là — sans analyse supplémentaire, la confiance étant directe.

## 4. Fonctionnement étape par étape

1. **Identification des cas à examiner** (`find_excluded_candidates`) : lignes de `REPLACEMENT_DECISIONS.csv` où `Action == "garder_original"` **et** `Verdict_automatique` est `A_VERIFIER` ou `SUSPECT_ANNONCE`. Les exclusions déjà tranchées manuellement (raison commençant par `"OVERRIDE MANUEL"`) sont **ignorées** — elles ont déjà été vérifiées et confirmées, pas besoin de rechercher une alternative.
2. **Recherche d'une alternative** (`find_alternative_in_comparison_csv`) : lecture du CSV de comparaison correspondant, filtrage des candidats "En ligne" avec plus d'une page, sélection du plus léger parmi eux.
3. **Téléchargement** de l'alternative trouvée, si elle existe, dans `smart_test_output/<ENTREPRISE>/<ANNEE>_candidat_alternatif.pdf`.
4. **Mise à jour automatique de `overrides.csv`** : une nouvelle ligne est ajoutée (jamais les lignes existantes ne sont modifiées), avec `Action=remplacer` et une raison explicite (`"RESCUE AUTO : alternative >1 page trouvée..."`).

## 5. Utilisation

```bash
python rescue_excluded_candidates.py --decisions smart_test_output/REPLACEMENT_DECISIONS.csv
```

| Argument | Description | Défaut |
|---|---|---|
| `--decisions` | Fichier de décisions produit par `generate_replacement_decisions.py` | `smart_test_output/REPLACEMENT_DECISIONS.csv` |
| `--overrides` | Fichier d'overrides à compléter automatiquement | `overrides.csv` |
| `--report` | Fichier de rapport du sauvetage | `smart_test_output/RESCUE_REPORT.csv` |

## 6. Sorties produites

| Fichier | Contenu |
|---|---|
| `smart_test_output/<ENTREPRISE>/<ANNEE>_candidat_alternatif.pdf` | Le candidat alternatif téléchargé, si trouvé |
| `smart_test_output/RESCUE_REPORT.csv` | Détail de chaque cas examiné (alternative trouvée ou non) |
| `overrides.csv` | Mis à jour automatiquement avec les nouvelles alternatives trouvées |

Le rapport `RESCUE_REPORT.csv` contient, pour chaque (Entreprise, Année) examinée : le statut (`ALTERNATIVE_TROUVEE` / `AUCUNE_ALTERNATIVE`), le titre et le nombre de pages de l'alternative, et son URL.

## 7. Étape suivante

Si des alternatives ont été trouvées et ajoutées à `overrides.csv`, il faut **relancer `generate_replacement_decisions.py`** pour que ces nouvelles décisions soient intégrées dans `REPLACEMENT_DECISIONS.csv` — ce script le rappelle explicitement dans son résumé final.

## 8. Limites connues

- Ce script dépend entièrement des CSV de comparaison déjà générés par `smart_scrape_batch.py` : si ceux-ci ont été supprimés ou ne couvrent pas certaines années, aucune alternative ne pourra être trouvée pour ces cas, même si elle existe réellement en ligne.
- La règle de confiance ">1 page = fiable" est une heuristique validée empiriquement par l'utilisateur sur les cas rencontrés jusqu'ici, pas une garantie théorique absolue.
- Le script ne relance aucune analyse de qualité sur l'alternative trouvée (pas de passage par `verify_candidates_quality.py`) : la confiance est accordée uniquement sur le critère "nombre de pages".
