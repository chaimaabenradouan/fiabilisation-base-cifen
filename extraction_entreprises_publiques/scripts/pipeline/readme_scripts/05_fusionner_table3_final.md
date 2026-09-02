# Documentation du script `05_fusionner_table3_final.py`

**Objectif** : Fusionner le fichier `fusion_finale.csv` (indicateurs économiques déjà fusionnés) avec le CSV des **Immobilisations corporelles** (Tableau 3), pour produire le fichier final `datafinale.csv`.

---

## 1. Présentation générale

Ce script réalise la **dernière fusion** de la chaîne de traitement. Il combine :

- **Fichier principal** (`fusion_finale.csv`) → contient déjà les données du Tableau 1 + Tableau 2
- **Fichier secondaire** (`toutes_entreprises_table3_v1.csv`) → ajoute uniquement les colonnes d’actifs corporels

Caractéristiques :
- Jointure sur la colonne `_dossier`
- **Left join** : toutes les entreprises du fichier principal sont conservées
- Exclusion systématique des colonnes techniques de diagnostic (`_diag_avg_score`, `_warning_ancre`)

---

## 2. Chemins utilisés

```python
FILE1  = Path("../output/fusion_finale.csv")                 # indicateurs principaux
FILE2  = Path("../output/toutes_entreprises_table3_v1.csv")  # immobilisations corporelles
OUTPUT = Path("../output/datafinale.csv")                    # fichier final
```

Ces chemins peuvent être adaptés selon l’organisation des dossiers.

---

## 3. Logique de fusion

### 3.1 Colonnes exclues

```python
EXCLUDE = {"_diag_avg_score", "_warning_ancre"}
```

Ces colonnes techniques (scores de confiance et avertissements d’ancres) sont systématiquement retirées du résultat final, quel que soit le fichier d’origine.

### 3.2 Sélection des colonnes du Tableau 3

```python
cols_to_add = [c for c in df2.columns
               if c not in EXCLUDE and c != "_dossier"]
```

On conserve toutes les colonnes du Tableau 3 **sauf** :
- la clé `_dossier`
- les colonnes de diagnostic

### 3.3 Type de jointure

```python
merged = df1.merge(df2_clean, on="_dossier", how="left", suffixes=("", "_immo"))
```

- `how="left"` → toutes les entreprises de `fusion_finale.csv` sont conservées
- Si une entreprise n’a pas de données d’immobilisations corporelles, les colonnes correspondantes restent vides

---

## 4. Étapes du traitement

1. Lecture des deux CSV en `dtype=str` (évite les conversions automatiques)
2. Nettoyage des noms de colonnes (suppression des espaces éventuels)
3. Sélection des colonnes utiles du Tableau 3
4. Fusion left join sur `_dossier`
5. Suppression éventuelle des colonnes de diagnostic restantes
6. Écriture du fichier `datafinale.csv`

---

## 5. Fichier de sortie

| Fichier              | Description                                      |
|----------------------|--------------------------------------------------|
| `datafinale.csv`     | Fichier final contenant toutes les données       |

Le script affiche à la fin :
- Le chemin complet du fichier créé
- Le nombre de lignes et de colonnes
- La liste des colonnes d’immobilisations corporelles ajoutées

---

## 6. Place dans la chaîne de traitement

```
01_extraire_table1.py
02_extraire_table2.py
03_extraire_table3.py
04_fusionner_table1_table2.py
05_fusionner_table3_final.py     ← ce script
06_valider_donnees_financieres.py
```

Ce script produit le fichier de données consolidé qui sera ensuite validé par le script suivant.

---

## 7. Points importants

- Les fichiers sont lus en `dtype=str` pour préserver le format original des valeurs.
- Les colonnes techniques de diagnostic ne polluent pas le fichier final.
- Le left join garantit qu’aucune entreprise du fichier principal n’est perdue.
- Le script est simple et linéaire : il n’y a pas d’option en ligne de commande.

---

## 8. Conclusion

Le script `05_fusionner_table3_final.py` finalise la consolidation des données en ajoutant les informations d’immobilisations corporelles au reste des indicateurs.  
Il produit le fichier `datafinale.csv`, prêt pour l’étape de validation.
