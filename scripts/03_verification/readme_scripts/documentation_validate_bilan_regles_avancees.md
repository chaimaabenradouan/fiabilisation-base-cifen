# Documentation — `validate_bilan_regles_avancees.py`

## 1. Objectif du script

Ce script constitue le **deuxième niveau de contrôle qualité**, plus fin que `validate_bilan.py`. Là où le premier script vérifie uniquement la cohérence globale entre Actif, Passif et CPC, celui-ci vérifie la **construction interne de chaque sous-total** du Bilan et du CPC : chaque total doit être égal à la somme (ou à la différence) de ses composantes.

Il permet ainsi, en cas d'incohérence détectée, de **localiser précisément** quelle rubrique comptable est probablement mal extraite, plutôt que de simplement savoir que "quelque chose ne va pas" au niveau global.

Le script produit également des **statistiques d'extraction** (taux de remplissage des champs), indépendantes de la cohérence comptable : elles répondent à la question "le pipeline a-t-il réussi à extraire une valeur pour ce champ ?", peu importe si cette valeur est ensuite cohérente ou non.

## 2. Principe général des règles

Chaque règle vérifiée est de la forme :

- **Mode `sum`** : `Total == composante_1 + composante_2 + ... + composante_n`
- **Mode `diff`** : `Résultat == composante_1 − composante_2 − ... − composante_n`

Le script contient **26 règles actives**, couvrant :

- Les sous-totaux de rubriques de l'**Actif** (A à G, trésorerie).
- Les totaux généraux de l'**Actif** (TOTAL_I, TOTAL_II, TOTAL_GENERAL).
- Les sous-totaux de rubriques du **Passif** (A à F, trésorerie).
- Les totaux généraux du **Passif** (TOTAL_I, TOTAL_II, TOTAL_GENERAL).
- Les résultats intermédiaires du **CPC** (résultat d'exploitation, résultat financier, résultat courant, résultat non courant, résultat avant impôt, résultat net, totaux produits/charges).

### Règle volontairement retirée

La règle `CPC_I = I_1..I_8` (composition du total des produits d'exploitation) a été **désactivée** car elle générait trop de faux positifs nécessitant une vérification manuelle coûteuse en temps. Les règles qui utilisent `CPC_I` en amont (`CPC_III`, `CPC_VII`, `CPC_XI`, `CPC_TOTAL_PRODUITS`) restent actives : elles utilisent directement la valeur de `CPC_I` telle qu'extraite, sans revérifier sa propre composition.

## 3. Gestion des entreprises hors périmètre

Certaines entreprises ne peuvent, par construction, pas respecter le référentiel CGNC "commerce/industrie" standard utilisé comme base pour ces règles :

| Entreprise | Raison de l'exclusion |
|---|---|
| `CFG_BANK` | Banque : plan comptable bancaire, différent du CGNC commerce/industrie |
| `CASH_PLUS_S.A` | Établissement de paiement : structure de bilan différente |
| `ENNAKL_AUTOMOBILES` | Société tunisienne : ne suit pas la nomenclature CGNC marocaine |

Ces entreprises sont exclues du calcul du **taux corrigé** (qui reflète la qualité réelle du pipeline sur son périmètre cible), mais :
- elles restent visibles dans tous les fichiers détaillés (rien n'est supprimé) ;
- elles apparaissent toujours dans le **taux brut** (calculé sur l'ensemble des entreprises).

Cette liste est explicitement pensée pour être complétée (commentaire `# A COMPLETER` dans le code) au fur et à mesure que d'autres entreprises hors périmètre seraient identifiées.

## 4. Gestion des valeurs manquantes

Le script distingue trois cas, documentés en tête de fichier :

1. **Composante manquante (vide)** : traitée comme `0` dans la somme, conformément à la pratique comptable où une rubrique vide vaut 0.
2. **Colonne "total" elle-même vide** : la règle n'est pas évaluable pour cette ligne (rien à comparer) ; ce n'est pas compté comme une anomalie, mais signalé séparément dans les statistiques de **couverture** (`n_lignes_evaluables` vs `n_lignes_total`).
3. **Toutes les colonnes composantes d'une règle absentes du fichier** (pas juste vides, mais la colonne n'existe pas) : la règle est **désactivée globalement**, avec un avertissement affiché au lancement (`⚠️ Règle ignorée...`).

## 5. Fonctionnement technique, étape par étape

### 5.1. Chargement des données (`load_data`)
Identique au premier script : lecture CSV (séparateur `;`), conversion numérique de toutes les colonnes sauf `Entreprise` et `Annee`.

### 5.2. Calcul de la valeur attendue (`compute_expected`)
Pour chaque règle et chaque ligne, calcule la valeur théorique à partir des composantes (somme ou différence), en remplaçant les composantes manquantes par `0`.

### 5.3. Application des règles (`check_rules`)
Pour chaque règle active :
- Comparaison entre la valeur réelle (colonne "total") et la valeur attendue (calculée).
- Une ligne est jugée conforme si `|réel − attendu| <= tolérance`.
- Calcul d'un **taux de cohérence par règle** = nombre de lignes conformes / nombre de lignes évaluables.

**Important** : la sortie de cette étape ne contient **aucune valeur comptable individuelle** (ni réelle, ni calculée) — uniquement des identifiants (Entreprise, Année, nom de la règle en anomalie). Ce choix, documenté explicitement dans le code, évite d'avoir à vérifier/corriger des écarts un par un dans un fichier détaillé, et concentre la sortie sur des **indicateurs agrégés**.

### 5.4. Synthèses par Entreprise / Année (`build_summaries`)
Deux tables de synthèse sont construites à partir du détail des anomalies :

- **`par_entreprise_annee`** : une ligne par (Entreprise, Année) touchée par au moins une anomalie, avec le nombre d'anomalies et la liste des règles en défaut.
- **`par_entreprise`** : une ligne par entreprise, agrégée sur toutes ses années, avec :
  - `n_annees_total` : nombre d'années présentes dans le fichier ;
  - `n_annees_en_anomalie` : nombre d'années avec au moins une anomalie ;
  - `pct_annees_propres` : % d'années sans aucune anomalie ;
  - `n_anomalies_total` : nombre total d'anomalies (toutes années confondues) ;
  - `regles_en_anomalie` : ensemble des règles jamais en défaut pour cette entreprise.

### 5.5. Statistiques d'extraction (`build_extraction_stats`)
Indépendamment de toute règle comptable, le script calcule le **taux de remplissage** des champs CIFEN à trois niveaux :

1. **Global** : % de cellules non vides sur l'ensemble du fichier.
2. **Par entreprise** : taux de remplissage moyen sur toutes les lignes/années de chaque entreprise (utile pour repérer les entreprises les moins bien extraites).
3. **Par champ CIFEN** : taux de remplissage de chaque colonne (utile pour repérer les champs systématiquement mal reconnus par l'OCR/le mapping).

Ces statistiques sont calculées à la fois en **brut** (toutes entreprises) et en **corrigé** (hors périmètre exclu, cf. section 3).

## 6. Utilisation

```bash
python validate_bilan_regles_avancees.py chemin/vers/fichier.csv \
    --tolerance 1.0 \
    --entreprise "NOM_ENTREPRISE"
```

| Argument | Obligatoire | Description | Valeur par défaut |
|---|---|---|---|
| `fichier` | Oui | Chemin du fichier CSV à valider (séparateur `;`) | — |
| `--tolerance` | Non | Écart absolu toléré | `1.0` |
| `--out-extraction-global` | Non | Taux d'extraction global (brut + corrigé) | `taux_extraction_global.csv` |
| `--out-extraction-entreprise` | Non | Taux d'extraction par entreprise | `taux_extraction_par_entreprise.csv` |
| `--out-extraction-champ` | Non | Taux d'extraction par champ CIFEN | `taux_extraction_par_champ.csv` |
| `--out-global` | Non | Taux global unique de cohérence (brut + corrigé) | `taux_global.csv` |
| `--out-coverage` | Non | Taux de cohérence détaillé par règle | `couverture_regles.csv` |
| `--out-par-entreprise-annee` | Non | Synthèse des anomalies par (Entreprise, Année) | `anomalies_par_entreprise_annee.csv` |
| `--out-par-entreprise` | Non | Synthèse des anomalies par entreprise (toutes années) | `anomalies_par_entreprise.csv` |
| `--entreprise` | Non | Affiche en détail l'historique d'une seule entreprise (le fichier de sortie contient toujours toutes les entreprises) | Aucun (aucun zoom) |

## 7. Sorties produites (7 fichiers CSV)

| Fichier | Contenu |
|---|---|
| `taux_extraction_global.csv` | Taux de remplissage global, en brut et corrigé |
| `taux_extraction_par_entreprise.csv` | Taux de remplissage par entreprise, trié du plus faible au plus élevé |
| `taux_extraction_par_champ.csv` | Taux de remplissage par champ CIFEN, trié du plus faible au plus élevé |
| `taux_global.csv` | **Le chiffre clé** : taux global de cohérence comptable (brut + corrigé), toutes règles confondues |
| `couverture_regles.csv` | Taux de cohérence détaillé, règle par règle |
| `anomalies_par_entreprise_annee.csv` | Détail des (Entreprise, Année) en anomalie, avec les règles concernées |
| `anomalies_par_entreprise.csv` | Synthèse par entreprise, toutes années confondues |

À noter : **aucun de ces fichiers ne contient de valeur comptable individuelle** (réelle ou calculée) — uniquement des identifiants, des comptages et des pourcentages, conformément au choix de conception documenté dans le script.

## 8. Affichage console

Le script affiche, dans l'ordre :
1. La liste des entreprises hors périmètre détectées dans le fichier (le cas échéant).
2. Le taux d'extraction global (brut et corrigé), suivi du top 10 des entreprises et des champs les moins bien extraits.
3. Le taux global de cohérence comptable (brut et corrigé) — c'est l'indicateur de synthèse le plus important.
4. Le détail du taux de cohérence par règle.
5. Le résumé par entreprise (toutes années confondues).
6. Le détail par (Entreprise, Année) pour les lignes en anomalie.
7. Si l'option `--entreprise` est utilisée, un zoom sur l'historique de cette entreprise spécifique.

## 9. Limites connues

- La liste des entreprises hors périmètre est **manuelle** et doit être maintenue à jour à mesure que de nouveaux cas particuliers sont identifiés.
- Une composante manquante étant traitée comme `0`, une rubrique **totalement non extraite** (au lieu d'être réellement nulle) peut artificiellement faire apparaître une règle comme respectée ou, au contraire, en anomalie selon les cas — d'où l'intérêt de croiser ce script avec les statistiques d'extraction (taux de remplissage) pour ne pas confondre "donnée à 0" et "donnée manquante".
- La règle sur `CPC_I` a été volontairement désactivée (cf. section 2), ce qui limite la détection d'anomalies sur la composition détaillée des produits d'exploitation.
- Comme pour le premier script, la tolérance de `1.0` par défaut est un paramètre ajustable selon le niveau de précision souhaité.

## 10. Complémentarité avec `validate_bilan.py`

| | `validate_bilan.py` | `validate_bilan_regles_avancees.py` |
|---|---|---|
| Niveau de contrôle | Global (Actif = Passif = CPC) | Détaillé (composition de chaque sous-total) |
| Nombre de règles | 1 règle (2 égalités) | 26 règles |
| Sortie | Détail des valeurs en anomalie | Uniquement des indicateurs agrégés (comptages, %) |
| Usage typique | Diagnostic rapide de cohérence globale | Localisation fine de l'origine d'une erreur d'extraction |

En pratique, on peut utiliser `validate_bilan.py` pour un premier diagnostic rapide, puis `validate_bilan_regles_avancees.py` pour identifier précisément quelles rubriques comptables posent problème lorsqu'une incohérence globale est détectée.
