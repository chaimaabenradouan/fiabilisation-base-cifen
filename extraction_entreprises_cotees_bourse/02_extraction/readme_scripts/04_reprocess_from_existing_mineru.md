# `reprocess_from_existing_mineru.py`

## Rôle dans le pipeline

Script de **retraitement** : il réapplique la logique de sélection de
`mineru_extract_tables.py` (celle qui choisit les 4 tableaux pertinents à
partir de tous les tableaux détectés) **sans jamais relancer MinerU ni
l'OCR**. Il relit uniquement les `*_content_list.json` déjà produits lors
d'un run précédent — fichiers qui contiennent déjà le HTML des tableaux, les
légendes, et les chemins vers les images PNG déjà extraites.

```
content_list.json déjà existant (run précédent)
        │  (aucun appel à MinerU)
        ▼
[reprocess_from_existing_mineru.py]  ──►  *_tables_analysis.json corrigé
                                          + selected_tables/*.png corrigées
```

## Pourquoi ce script existe

MinerU (l'étape OCR/localisation la plus lourde du pipeline, plusieurs
secondes à minutes par PDF selon la taille) est la partie la plus coûteuse en
temps de calcul. La **logique de sélection** en aval (scoring des mots-clés,
détection de la série sociale/consolidée, réparation des bilans coupés en
deux blocs) évolue en revanche fréquemment, au fur et à mesure que des bugs
sont découverts sur des cas réels (voir les correctifs documentés dans le
code : cas CMGP_GROUP, ZELLIDJA S.A., CASH_PLUS S.A...).

Sans ce script, corriger un bug de logique obligerait à **relancer MinerU sur
l'ensemble du corpus** (des centaines de PDF), pour un coût de plusieurs
heures. Ce script permet de rejouer uniquement les étapes B à F du pipeline
(lecture, scoring, réparation, sélection, export) en quelques secondes par
document — un coût quasi identique à celui de l'audit.

## Fonctionnement

Le script **importe directement** les fonctions de `mineru_extract_tables.py`
(`load_content_blocks`, `build_table_candidates`, `detect_serie_context`,
`score_all_candidates`, `repair_partial_bilan_tables`,
`add_neighbor_coherence_reasoning`, `select_coherent_serie`,
`mark_selection`, `build_output_json`, `export_selected_images`) plutôt que de
dupliquer le code — garantissant que la logique retraitée est **exactement**
la même que celle utilisée pour un traitement neuf, sans risque de
divergence.

Deux modes de sortie :
- **`--in-place`** : écrit le JSON et `selected_tables/` corrigés directement
  à côté du `content_list.json` trouvé (écrase les anciens résultats).
- **Dossier séparé** (`--output-root`) : crée un sous-dossier par document
  sans toucher aux résultats originaux — utile pour comparer avant/après une
  correction.

## Utilisation (CLI)

```bash
# Parcourt tout un dossier racine, écrase les résultats en place
python reprocess_from_existing_mineru.py --root-dir /chemin/vers/output --in-place

# Ou écrit dans un dossier séparé, pour comparaison
python reprocess_from_existing_mineru.py --root-dir /chemin/vers/output \
    --output-root /chemin/vers/output_corrige
```

| Argument | Rôle | Défaut |
|---|---|---|
| `--root-dir` | Dossier racine où chercher récursivement les `*_content_list.json` existants | obligatoire |
| `--in-place` | Écrase les résultats à côté du `content_list.json` d'origine | désactivé |
| `--output-root` | Dossier où créer un sous-dossier par document (si pas `--in-place`) | `./output_corrige/<pdf>/` |
| `--serie-preference` | `social` ou `consolide` en cas d'égalité | `social` |

## Cas d'usage typique dans le pipeline

```
01_run_all_reports.py      → traitement initial de tout le corpus
02_audit_selected_tables.py → détecte des cas suspects
        │
        ▼  (analyse manuelle du bug, correction dans mineru_extract_tables.py)
        │
04_reprocess_from_existing_mineru.py  → retraite tout le corpus corrigé, en quelques minutes
02_audit_selected_tables.py            → re-vérifie que les cas sont résolus
```

## Pourquoi ce script illustre une démarche professionnelle

- Il sépare clairement les coûts **irréversibles** (OCR/MinerU) des coûts
  **itératifs** (logique de sélection), ce qui est une bonne pratique
  d'ingénierie de pipeline de données.
- Il élimine tout risque de divergence de logique entre un traitement neuf et
  un retraitement, en réutilisant le même code source plutôt qu'en le
  dupliquant.
- Il permet un cycle **correction → vérification** rapide, essentiel pour
  fiabiliser un pipeline appliqué à un grand nombre de documents hétérogènes.
