# Documentation — `validate_bilan.py`

## 1. Objectif du script

Ce script constitue le **premier niveau de contrôle qualité** des données comptables extraites automatiquement (via le pipeline `cifen_extractor.py`) à partir des bilans (Actif/Passif) et des Comptes de Produits et Charges (CPC) d'entreprises cotées, selon le référentiel comptable marocain (CGNC).

Son rôle est de vérifier une **règle de cohérence fondamentale** qui relie les trois documents comptables entre eux : si cette règle est respectée, on peut avoir un premier niveau de confiance dans la qualité de l'extraction pour la ligne (Entreprise, Année) concernée.

## 2. Contexte comptable

En comptabilité marocaine (CGNC), trois documents doivent être mutuellement cohérents :

- **Le Bilan Actif** : liste tout ce que l'entreprise possède (immobilisations, stocks, créances, trésorerie...).
- **Le Bilan Passif** : liste comment ces actifs sont financés (capitaux propres, dettes, résultat net...).
- **Le CPC (Compte de Produits et Charges)** : détaille la formation du résultat net de l'exercice (produits moins charges).

Le principe comptable de base impose que :

1. **L'équilibre du bilan** : le Total Général de l'Actif doit être strictement égal au Total Général du Passif (principe de la partie double).
2. **Le raccordement du résultat** : le résultat net calculé dans le CPC (ligne XIII, "Résultat net") doit être le même montant que celui inscrit au Passif à la ligne A12 (le résultat net fait partie des capitaux propres au Passif).

## 3. Règle vérifiée par le script

Une seule règle croisée, mais en deux volets, est appliquée à **chaque ligne (Entreprise, Année)** du fichier :

| Volet | Égalité vérifiée | Signification |
|---|---|---|
| Bilan | `Actif_TOTAL_GENERAL == Passif_TOTAL_GENERAL` | Le bilan est équilibré |
| Résultat | `CPC_XIII == Passif_A12` | Le résultat net du CPC correspond bien à celui inscrit au Passif |

Une ligne est jugée **cohérente** (`Actif = Passif = CPC`) seulement si les **deux** égalités sont vérifiées simultanément.

### Point d'attention documenté dans le code

Le script précise explicitement une source de confusion possible dans le mapping du pipeline d'extraction : la colonne `CPC_XIV` correspond au champ *"Résultat par action"* et **non** au résultat net. C'est bien `CPC_XIII` (ligne "Résultat net (XI-XII)") qui doit être utilisé pour cette vérification. Cette précision évite une erreur d'interprétation qui fausserait tout le contrôle.

## 4. Colonnes requises

Le script a besoin des 4 colonnes suivantes pour fonctionner :

- `Actif_TOTAL_GENERAL`
- `Passif_TOTAL_GENERAL`
- `Passif_A12` (résultat net inscrit au Passif)
- `CPC_XIII` (résultat net du CPC)

Si l'une de ces colonnes est absente du fichier, le script s'arrête avec une erreur explicite (`ValueError`) indiquant quelle(s) colonne(s) manque(nt).

## 5. Fonctionnement technique, étape par étape

### 5.1. Chargement des données (`load_data`)
- Lecture du CSV avec séparateur `;` et encodage `utf-8`.
- Toutes les colonnes sauf `Entreprise` et `Annee` sont converties en valeurs numériques (`pd.to_numeric`), les valeurs non convertibles devenant `NaN` (donnée manquante).

### 5.2. Vérification de la règle (`check_rule`)
Pour chaque ligne du fichier :
1. Calcul de l'écart bilan : `Actif_TOTAL_GENERAL - Passif_TOTAL_GENERAL`.
2. Calcul de l'écart résultat : `CPC_XIII - Passif_A12`.
3. Une égalité est considérée vérifiée si l'écart absolu est **inférieur ou égal à la tolérance** définie (par défaut `1.0`, pour absorber les arrondis).
4. Si l'une des deux égalités échoue (ou si une donnée est manquante, `NaN`), la ligne est enregistrée comme **anomalie**, avec le détail des valeurs et des écarts.

Le script calcule également trois **taux de cohérence** sur l'ensemble du fichier :
- `taux_coherence_bilan_pct` : % de lignes où Actif = Passif.
- `taux_coherence_resultat_pct` : % de lignes où CPC = Passif (résultat).
- `taux_coherence_global_pct` : % de lignes où les deux conditions sont vérifiées.

### 5.3. Traitement des valeurs manquantes
Si une des quatre colonnes nécessaires est vide (`NaN`) pour une ligne donnée, l'écart correspondant ne peut pas être calculé : la condition est automatiquement considérée comme **non vérifiée**, et la ligne apparaît en anomalie (avec les écarts affichés comme `NaN` pour indiquer que la donnée manque, plutôt qu'une réelle incohérence numérique).

## 6. Utilisation

```bash
python validate_bilan.py chemin/vers/fichier.csv --tolerance 1.0 --out anomalies.csv
```

| Argument | Obligatoire | Description | Valeur par défaut |
|---|---|---|---|
| `fichier` | Oui | Chemin du fichier CSV à valider (séparateur `;`) | — |
| `--tolerance` | Non | Écart absolu toléré entre les valeurs comparées | `1.0` |
| `--out` | Non | Fichier de sortie listant le détail des anomalies | `anomalies.csv` |

## 7. Sorties produites

### 7.1. Affichage console
- Nombre de lignes et colonnes chargées.
- Les trois taux de cohérence (bilan, résultat, global), avec le nombre de lignes concernées.
- Le détail complet des anomalies (si présentes), affiché directement dans le terminal.

### 7.2. Fichier CSV d'anomalies (`--out`)
Un fichier CSV contenant, pour chaque ligne en anomalie, les colonnes suivantes :

| Colonne | Description |
|---|---|
| `Entreprise` | Nom de l'entreprise |
| `Annee` | Année de l'exercice |
| `Regle` | Nom de la règle violée (`Cohérence Actif = Passif = CPC`) |
| `Actif_TOTAL_GENERAL` | Valeur extraite |
| `Passif_TOTAL_GENERAL` | Valeur extraite |
| `Ecart_Actif_Passif` | Écart calculé (Actif − Passif) |
| `CPC_XIII` | Résultat net du CPC extrait |
| `Passif_A12` | Résultat net au Passif extrait |
| `Ecart_Resultat_CPC_Passif` | Écart calculé (CPC − Passif) |

Ce fichier n'est généré que s'il existe au moins une anomalie.

## 8. Limites connues

- La tolérance par défaut (`1.0`) est un choix arbitraire destiné à absorber les erreurs d'arrondi ; elle peut être ajustée selon la précision attendue.
- Le script ne vérifie **que** la cohérence globale entre les trois documents ; il ne contrôle pas la cohérence interne des sous-totaux (rôle du second script, `validate_bilan_regles_avancees.py`).
- Une ligne avec une donnée manquante est automatiquement classée en anomalie, même si les données présentes sont par ailleurs cohérentes — ce choix privilégie la prudence (on préfère signaler un doute plutôt que de le masquer).

## 9. Complémentarité avec le second script

Ce script donne une **vue synthétique et rapide** ("les trois documents se recoupent-ils au global ?"), alors que `validate_bilan_regles_avancees.py` va plus loin en vérifiant la construction interne de chaque sous-total (ex. `Actif_A = A1+A2+A3`), ce qui permet, en cas d'anomalie détectée ici, d'identifier plus précisément où se situe l'erreur d'extraction.
