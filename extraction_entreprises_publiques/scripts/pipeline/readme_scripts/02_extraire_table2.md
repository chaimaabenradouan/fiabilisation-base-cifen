# Documentation du script `02_extraire_table2.py`

**Objectif** : Parcourir toutes les entreprises et extraire le **Tableau 2** (Indicateurs économiques et financiers), en utilisant des ancres dynamiques pour déterminer précisément le début et la fin de la zone à extraire.

---

## 1. Présentation générale

Ce script fait partie de la chaîne de traitement des pages d’entreprises. Il est le pendant du script `01_extraire_table1.py` et s’occupe exclusivement du **Tableau 2**.

Points clés :
- Utilise `find_section_anchors` pour localiser dynamiquement :
  - le début du tableau → bandeau « Indicateurs économiques et financiers »
  - la fin du tableau → bandeau « Gouvernance »
- Cette approche est indispensable car la hauteur de l’en-tête varie d’une page à l’autre.
- Produit pour chaque entreprise un JSON + un CSV individuels.
- Produit également un **CSV global** regroupant toutes les entreprises.

---

## 2. Dépendances et chemins

```python
from projet_2.scripts.lib.extract_table2 import extract_table2
from projet_2.scripts.lib.anchors import find_section_anchors
```

- `extract_table2` : fonction spécialisée dans l’extraction des indicateurs du Tableau 2.
- `find_section_anchors` : détection des positions verticales des grandes sections de la page.

**Chemins utilisés** :
- Dossier source : `../entreprises`
- Fichier de sortie global : `../output/toutes_entreprises_table2_v1.csv`

---

## 3. Fonctionnement détaillé

### 3.1 Récupération des dossiers entreprises

```python
folders = sorted([p for p in ENTREPRISES_DIR.iterdir() if p.is_dir()])
```

Liste ordonnée de tous les dossiers d’entreprises.

### 3.2 Traitement d’une entreprise

Pour chaque dossier :

1. **Vérification de `page.png`**
   ```python
   if not page_path.exists():
       print(f"⚠️  {folder.name} → page.png manquant")
       continue
   ```

2. **Ouverture de l’image**
   ```python
   img = Image.open(page_path).convert("RGB")
   ```

3. **Calcul dynamique de `y_start` et `y_end`**
   ```python
   anchors = find_section_anchors(img)
   y_start = anchors.get("indicateurs_financiers", 0.38 * img.height)
   y_end   = anchors.get("gouvernance", 0.70 * img.height)
   ```
   - Si l’ancre « indicateurs_financiers » est absente → repli sur `0.38 * hauteur`
   - Si l’ancre « gouvernance » est absente → repli sur `0.70 * hauteur`
   - Dans les deux cas, un avertissement est ajouté dans le résultat.

4. **Extraction du Tableau 2**
   ```python
   result = extract_table2(
       img,
       y_start=y_start,
       y_end=y_end,
       x_frac_end=0.75,   # limite horizontale à 75 % de la largeur
   )
   ```

5. **Ajout des métadonnées**
   - Flag d’avertissement si une ancre de repli a été utilisée
   - Nom du dossier (`_dossier`)

6. **Sauvegarde individuelle**
   - `table2_indicateurs_v1.json`
   - `table2_indicateurs_v1.csv` (format champ / valeur)

### 3.3 Génération du CSV global

À la fin du traitement :

```python
all_keys = sorted({k for row in all_results for k in row.keys()})
```

Crée un unique CSV contenant l’union de toutes les colonnes rencontrées.

---

## 4. Fichiers générés

### Par entreprise
| Fichier                        | Description                              |
|-------------------------------|------------------------------------------|
| `table2_indicateurs_v1.json`  | Résultat complet au format JSON          |
| `table2_indicateurs_v1.csv`   | Même résultat en CSV (champ / valeur)    |

### Global
| Fichier                                         | Description                          |
|------------------------------------------------|--------------------------------------|
| `../output/toutes_entreprises_table2_v1.csv`   | Toutes les entreprises en un seul CSV|

---

## 5. Messages de suivi

Le script affiche :
- Le nombre total d’entreprises trouvées
- Le nom de l’entreprise en cours
- Le nombre d’indicateurs extraits (hors métadonnées)
- Les erreurs éventuelles

---

## 6. Points de robustesse

| Situation                                      | Comportement                                              |
|-----------------------------------------------|-----------------------------------------------------------|
| `page.png` manquant                           | Avertissement + passage à l’entreprise suivante           |
| Ancre « indicateurs_financiers » absente      | Repli sur 0.38 × hauteur + flag `_warning_ancre`          |
| Ancre « gouvernance » absente                 | Repli sur 0.70 × hauteur + flag `_warning_ancre`          |
| Exception quelconque                          | Affichage de l’erreur + continuation du traitement        |

---

## 7. Différences avec le script Tableau 1

| Aspect                  | Tableau 1 (`01_extraire_table1.py`)      | Tableau 2 (`02_extraire_table2.py`)          |
|-------------------------|------------------------------------------|----------------------------------------------|
| Zone extraite           | Haut de page → Indicateurs financiers   | Indicateurs financiers → Gouvernance         |
| Ancres utilisées        | 1 ancre (`indicateurs_financiers`)      | 2 ancres (`indicateurs_financiers` + `gouvernance`) |
| Paramètre horizontal    | `x_frac_end=None`                       | `x_frac_end=0.75`                            |
| Fichiers de sortie      | `table1_infos_v1.*`                     | `table2_indicateurs_v1.*`                    |

---

## 8. Limites connues

- Dépend de la qualité de détection des ancres par `find_section_anchors`.
- Les fractions de repli (0.38 et 0.70) peuvent être imprécises sur des pages atypiques.
- Aucune validation métier des valeurs extraites (laissé au script de validation ultérieur).

---

## 9. Place dans la chaîne de traitement

```
01_extraire_table1.py
02_extraire_table2.py          ← ce script
03_extraire_table3.py
04_fusionner_table1_table2.py
05_fusionner_table3_final.py
06_valider_donnees_financieres.py
```

---

## 10. Conclusion

Le script `02_extraire_table2.py` assure l’extraction robuste et automatisée des indicateurs économiques et financiers. Grâce aux ancres dynamiques, il s’adapte correctement à la variabilité de mise en page des documents, tout en conservant un mécanisme de repli sécurisé.
