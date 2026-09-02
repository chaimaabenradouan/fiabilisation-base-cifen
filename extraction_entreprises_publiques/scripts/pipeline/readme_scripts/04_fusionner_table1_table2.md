# Documentation du script `04_fusionner_table1_table2.py`

**Objectif** : Fusionner les CSV du Tableau 2 (fichier principal) et du Tableau 1 (fichier secondaire) sur la clé commune `_dossier`, en ne conservant que certains champs choisis du Tableau 1.

---

## 1. Présentation générale

Ce script réalise la **première fusion** de la chaîne de traitement. Il combine :

- **Table 2** (fichier principal) → **tous** ses champs sont conservés
- **Table 1** (fichier secondaire) → **seulement** les champs suivants sont ajoutés :
  - `activite`
  - `date_creation`
  - `sigle`
  - `capital_social`
  - `classification_juridique`

La fusion est un **OUTER JOIN** : aucune entreprise n’est perdue, qu’elle soit présente uniquement dans table2, uniquement dans table1, ou dans les deux.

---

## 2. Usage

```bash
python3 04_fusionner_table1_table2.py \
    toutes_entreprise_table2_FINAL.csv \
    toutes_entreprise_table1_v1.csv \
    --out toutes_entreprises_fusionnees.csv
```

| Argument       | Description                                      | Obligatoire |
|----------------|--------------------------------------------------|-------------|
| `table2_csv`   | CSV principal (tous les champs conservés)        | Oui         |
| `table1_csv`   | CSV secondaire (champs sélectionnés uniquement)  | Oui         |
| `--out`        | Chemin du fichier de sortie                      | Non (défaut : `toutes_entreprises_fusionnees.csv`) |

---

## 3. Logique de fusion

### 3.1 Clé de jointure

```python
KEY = "_dossier"
```

La colonne `_dossier` (nom du dossier de l’entreprise) sert de clé unique.

### 3.2 Sélection des champs de Table 1

```python
TABLE1_FIELDS_TO_KEEP = [
    "activite",
    "date_creation",
    "sigle",
    "capital_social",
    "classification_juridique",
]
```

Seuls ces champs sont récupérés depuis le CSV Table 1.  
Si un champ est absent du fichier Table 1, un avertissement est affiché et le champ est simplement ignoré.

### 3.3 Type de jointure

```python
merged = df2.merge(df1_reduced, on=KEY, how="outer", indicator=True)
```

- `how="outer"` → conserve **toutes** les entreprises des deux fichiers
- Les entreprises présentes uniquement dans table2 → colonnes table1 vides
- Les entreprises présentes uniquement dans table1 → colonnes table2 vides

### 3.4 Ordre final des colonnes

1. `_dossier` (clé)
2. Les champs provenant de table1
3. Tous les autres champs (provenant de table2)

---

## 4. Contrôles et alertes

Le script effectue plusieurs vérifications utiles :

| Contrôle                              | Comportement                                      |
|---------------------------------------|---------------------------------------------------|
| Colonne `_dossier` absente            | Arrêt du script avec message d’erreur             |
| Champs table1 manquants               | Avertissement + champs ignorés                    |
| Doublons de `_dossier`                | Avertissement listant les entreprises en double   |
| Entreprises présentes dans un seul fichier | Affichage de la liste (information)            |

---

## 5. Fichier de sortie

Le CSV généré contient :
- Une ligne par entreprise
- Toutes les colonnes de table2
- Les colonnes sélectionnées de table1
- Aucune perte d’entreprise

---

## 6. Place dans la chaîne de traitement

```
01_extraire_table1.py
02_extraire_table2.py
03_extraire_table3.py
04_fusionner_table1_table2.py     ← ce script
05_fusionner_table3_final.py
06_valider_donnees_financieres.py
```

Ce script prépare le fichier intermédiaire qui sera ensuite fusionné avec les données du Tableau 3.

---

## 7. Points importants

- Les fichiers sont lus en `dtype=str` pour éviter les conversions automatiques de types (nombres, dates…).
- Les doublons de clé sont détectés mais **ne bloquent pas** le script (ils d’attention uniquement).
- Le script est volontairement simple et transparent : toute anomalie est signalée clairement dans le terminal.

---

## 8. Conclusion

Le script `04_fusionner_table1_table2.py` assure une fusion propre et contrôlée entre les informations de base (Table 1) et les indicateurs économiques et financiers (Table 2).  
Il constitue une étape essentielle avant la fusion finale avec le Tableau 3.
