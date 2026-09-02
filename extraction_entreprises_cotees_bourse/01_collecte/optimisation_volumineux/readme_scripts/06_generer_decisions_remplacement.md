# Documentation — `06_generer_decisions_remplacement.py` (anciennement generate_replacement_decisions.py)

## 1. Rôle dans le pipeline

Ce script fait le **lien entre l'analyse automatique et la décision finale**. Il combine les verdicts automatiques de `verify_candidates_quality.py` avec d'éventuelles décisions manuelles de l'utilisateur (après avoir regardé les images de vérification), pour produire un fichier unique listant, pour chaque candidat, l'action à effectuer : `remplacer` ou `garder_original`. Il ne touche **à aucun fichier PDF**.

## 2. Règles de décision par défaut

Si aucune décision manuelle (override) n'existe pour une ligne donnée, l'action est déterminée uniquement par le verdict automatique (`DEFAULT_ACTION_BY_VERDICT`) :

| Verdict automatique | Action par défaut | Justification |
|---|---|---|
| `OK_MULTIPAGE` | `remplacer` | Validé manuellement : >1 page = fiable |
| `OK_AUTO` | `remplacer` | Tableau + mots-clés financiers détectés |
| `A_VERIFIER` | `garder_original` | Par prudence : la plupart se sont révélés être des faux lors des vérifications manuelles antérieures |
| `SUSPECT_ANNONCE` | `garder_original` | Communiqué vide confirmé |
| `FICHIER_INTROUVABLE` / `ERREUR_LECTURE` | `garder_original` | Rien d'exploitable |

## 3. Mécanisme d'override manuel (`overrides.csv`)

L'utilisateur peut fournir un fichier `overrides.csv` listant ses décisions manuelles après avoir examiné les images de `A_VERIFIER_VISUELLEMENT/`. Ce fichier a **priorité absolue** sur le verdict automatique.

Format attendu (colonnes) :

| Colonne | Description |
|---|---|
| `Entreprise` | Nom de l'entreprise |
| `Annee` | Année concernée |
| `Action` | `remplacer` ou `garder_original` (toute autre valeur est ignorée avec un avertissement) |
| `Raison` | Justification libre de la décision manuelle |
| `Fichier_candidat_override` | (Optionnel) chemin d'un fichier candidat alternatif à utiliser |
| `Pages_candidat_override` | (Optionnel) nombre de pages de ce candidat alternatif |

Si `overrides.csv` n'existe pas, le script continue simplement sans override (c'est un fichier optionnel).

## 4. Fonctionnement étape par étape

1. Chargement de `QUALITY_CHECK.csv` (verdicts automatiques).
2. Chargement de `overrides.csv` (décisions manuelles, optionnel), indexé par `(Entreprise, Annee)`.
3. Pour chaque ligne de `QUALITY_CHECK.csv` :
   - Si un override existe pour cette (Entreprise, Année) → l'action et le candidat viennent de l'override, avec la raison préfixée par `"OVERRIDE MANUEL : ..."`.
   - Sinon → l'action vient de la règle par défaut associée au verdict automatique.
4. Écriture du fichier final `REPLACEMENT_DECISIONS.csv`.

## 5. Utilisation

```bash
# Avec les chemins par défaut
python generate_replacement_decisions.py

# Avec des chemins personnalisés
python generate_replacement_decisions.py --quality smart_test_output/QUALITY_CHECK.csv --overrides overrides.csv
```

| Argument | Description | Défaut |
|---|---|---|
| `--quality` | Fichier de verdicts produit par `verify_candidates_quality.py` | `smart_test_output/QUALITY_CHECK.csv` |
| `--overrides` | Fichier des décisions manuelles (optionnel) | `overrides.csv` |
| `--out` | Fichier de sortie des décisions finales | `smart_test_output/REPLACEMENT_DECISIONS.csv` |

## 6. Sortie produite

**`smart_test_output/REPLACEMENT_DECISIONS.csv`** :

| Colonne | Description |
|---|---|
| `Entreprise`, `Annee` | Identifiants |
| `Action` | `remplacer` ou `garder_original` — **la colonne pilote pour `apply_replacements.py`** |
| `Verdict_automatique` | Le verdict d'origine (`OK_AUTO`, `A_VERIFIER`, etc.) |
| `Raison` | Explication de la décision (automatique ou override) |
| `Pages_locales_originales`, `Pages_candidat` | Comparaison des tailles |
| `Fichier_candidat` | Chemin du fichier candidat à utiliser en cas de remplacement |

L'utilisateur peut encore **ouvrir ce fichier et modifier manuellement la colonne `Action`** avant de lancer `apply_replacements.py` — le script le rappelle explicitement dans son résumé final.

## 7. Limites connues

- Le script fait confiance à `overrides.csv` sans re-vérifier que le fichier candidat indiqué (`Fichier_candidat_override`) existe réellement sur disque — cette vérification est faite plus tard par `apply_replacements.py`.
- Une action invalide dans `overrides.csv` (autre que `remplacer`/`garder_original`) est simplement ignorée avec un avertissement, la ligne concernée retombe donc sur la règle par défaut du verdict automatique.
