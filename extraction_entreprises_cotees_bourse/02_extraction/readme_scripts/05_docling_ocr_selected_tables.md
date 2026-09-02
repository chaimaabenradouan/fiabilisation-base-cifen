# `docling_ocr_selected_tables.py`

## Rôle dans le pipeline

Dernière étape du dossier `02_extraction/` : elle prend les **images**
sélectionnées par `mineru_extract_tables.py` (`identification.png`,
`bilan_actif.png`, `bilan_passif.png`, `cpc.png`) et effectue un **OCR
structuré** via la librairie **Docling** (moteur `TableFormer`) pour produire
des tableaux exploitables sous forme de **CSV**, prêts à être mappés dans la
base de données finale.

```
selected_tables/*.png  (images des 4 tableaux)
        │
        ▼
[docling_ocr_selected_tables.py]  ──►  tables_csv/*.csv
                                       + table_images/*.png (crops par table)
                                       + <document>_docling_tables.json
```

## Pipeline interne (par image)

1. **Conversion Docling** (`make_docling_converter`) : OCR + reconstruction de
   la structure du tableau (lignes/colonnes), en mode `TableFormerMode.ACCURATE`
   avec appariement de cellules (`do_cell_matching=True`) et une résolution
   d'image relevée à **`images_scale = 3.0`** (contre 2.0 par défaut) pour
   donner au modèle un signal visuel plus net sur les fines lignes de
   séparation entre rangées.
2. **Réalignement sur la nomenclature CGNC officielle**
   (`align_rows_to_expected_fields`) : correctif central de ce script.
3. **Correctifs OCR additionnels** spécifiques au CPC
   (`fix_ocr_artifacts_cpc`).
4. **Calcul de couverture** (`compute_field_coverage`) : pourcentage des
   champs CGNC attendus effectivement retrouvés dans le tableau OCRisé.
5. **Suggestions de récupération** (`find_recovery_suggestions`) : si un champ
   attendu est absent du tableau retenu, le script cherche s'il apparaît dans
   un **autre** tableau du même document (repli via `content_list.json`
   MinerU), pour orienter une correction manuelle.

## Le problème corrigé : la fusion de lignes OCR

### Constat (audit du cas AFMA_SA / 2016)
Quand une ligne du tableau financier n'a **aucune valeur numérique** (ex. un
sous-total vide) ou que deux libellés sont visuellement très proches,
TableFormer les fusionne parfois en **une seule ligne OCR** contenant
plusieurs libellés concaténés (ex. *"IMMOBILISATIONS INCORPORELLES (B)
Immobilisations en recherche et développement"*).

**Cause racine :** l'image PNG exportée par le script précédent est une image
**plate** (rasterisée), qui a perdu les traits vectoriels du PDF original —
Docling doit alors deviner la structure à partir des seuls pixels, et les
lignes à faible signal (peu ou pas de chiffres) sont les plus fragiles.

### Correctif : `align_rows_to_expected_fields`
S'appuie sur `EXPECTED_FIELDS` (la liste officielle et ordonnée des rubriques
CGNC) pour détecter qu'une ligne OCR correspond en réalité à la concaténation
de N libellés attendus consécutifs, et **éclate automatiquement** cette ligne
en N lignes propres, avec des règles strictes :
- les valeurs numériques restent attachées **uniquement** à la première ligne
  du groupe éclaté — **jamais** de valeur inventée ou dupliquée sans preuve ;
- chaque ligne issue d'un éclatement est **marquée explicitement** dans la
  colonne `Verification` du CSV, pour vérification humaine ultérieure ;
- une option `--no-align` permet de désactiver ce correctif si besoin de
  comparaison avec le comportement brut.

### Version dédiée au CPC : `align_rows_to_expected_fields_cpc`
Le CPC utilise une version plus sophistiquée (matching par **tokens** plutôt
que par séquence de caractères brute, fenêtre de recherche glissante locale,
non-éclatement systématique des lignes TOTAL/RÉSULTAT). Cette fonction
existait dans une révision antérieure du fichier sans jamais être appelée —
son branchement effectif dans `process_category()` fait partie des
correctifs de cette version. Des auto-tests (`--self-test`) valident ses
garanties clés (aucune invention de valeur, pas de décalage sur ligne
manquante, lignes TOTAL jamais éclatées...).

### Correctifs OCR additionnels (CPC uniquement)
- **Nombre collé au libellé** (ex. `"...titres immobilises7 054 597,78"`) :
  détecté et déplacé automatiquement dans la première colonne de valeur vide.
- **Ligne orpheline** (libellé vide, une seule valeur isolée) : fusionnée
  dans la ligne précédente, uniquement si la cellule cible y est vide (jamais
  d'écrasement d'une valeur déjà présente).

## Sorties

Pour chaque document traité :
- `tables_csv/{identification,bilan_actif,bilan_passif,cpc}.csv` — un CSV par
  catégorie, avec une colonne `Verification` signalant les lignes à
  contrôler manuellement.
- `table_images/*.png` — crops individuels de chaque tableau OCRisé.
- `<document>_docling_tables.json` — JSON complet (tableaux, couverture par
  champ CGNC, avertissements, suggestions de récupération).

## Mode batch

`run_batch()` parcourt automatiquement l'arborescence
`<root>/<ENTREPRISE>/<ANNÉE>/mineru_raw/<ANNÉE>/auto/selected_tables/`
(avec repli sur l'ancienne structure `<ANNÉE>/selected_tables/` si présente),
avec reprise automatique (`--skip-existing`) et journal d'erreurs
(`batch_errors_script2.log`).

## Utilisation (CLI)

```bash
# Un seul document
python docling_ocr_selected_tables.py --selected-dir output/SOCIETE/2022/selected_tables

# Mode batch sur tout un corpus
python docling_ocr_selected_tables.py --batch-root output --skip-existing

# Auto-tests du correctif CPC
python docling_ocr_selected_tables.py --self-test
```

| Argument | Rôle | Défaut |
|---|---|---|
| `--selected-dir` | Dossier `selected_tables/` d'un document unique | — |
| `--batch-root` | Traite tout un corpus en mode batch | — |
| `--images-scale` | Résolution du rendu image | `3.0` |
| `--no-align` | Désactive le correctif de fusion de lignes | activé |
| `--self-test` | Lance les auto-tests puis quitte | — |
| `--skip-existing` | Ignore les documents déjà traités (mode batch) | désactivé |

## Limite connue et piste d'amélioration (documentée dans le code)

Le correctif actuel répare le **symptôme** (lignes fusionnées) par
réalignement sur la liste officielle, mais la **cause racine** reste que
Docling travaille sur un PNG rasterisé, sans les traits vectoriels du PDF. Une
amélioration prévue mais non implémentée consisterait à exporter, en plus du
PNG, un **crop PDF vectoriel** (via `fitz`, limité au bbox du tableau) pour
les documents dont le texte natif n'est pas corrompu — ce qui redonnerait à
TableFormer l'accès aux vraies lignes de séparation.
