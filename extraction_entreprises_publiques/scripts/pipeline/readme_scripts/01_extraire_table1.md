# Documentation du script `process_all_table1.py`

**Objectif** : Parcourir toutes les entreprises d’un répertoire et extraire le **Tableau 1** (Informations de base) de chaque page, en utilisant une ancre dynamique pour déterminer la fin du tableau.

---

## 1. Présentation générale

Ce script automatise l’extraction du Tableau 1 pour l’ensemble des entreprises présentes dans le dossier `../entreprises`.

Points importants :
- Utilise une **ancre dynamique** (`find_section_anchors`) pour trouver la fin du Tableau 1 (début de la section « Indicateurs économiques et financiers »).
- Cette approche remplace l’ancienne méthode basée sur une fraction fixe de la hauteur de l’image (0.40 × hauteur), qui échouait lorsque le bandeau du nom d’entreprise faisait 1, 2 ou 3 lignes.
- Produit pour chaque entreprise un fichier JSON + un fichier CSV individuels.
- Produit également un **CSV global** regroupant toutes les entreprises.

---

## 2. Dépendances et chemins

```python
from projet_2.scripts.lib.extract_table1 import extract_table1
from projet_2.scripts.lib.anchors import find_section_anchors
```

- `extract_table1` : fonction qui réalise l’extraction proprement dite du Tableau 1.
- `find_section_anchors` : fonction qui détecte les positions verticales des grandes sections de la page.

**Chemins utilisés** :
- Dossier source : `../entreprises`
- Fichier de sortie global : `../output/toutes_entreprises_table1_v1.csv`

---

## 3. Fonctionnement détaillé

### 3.1 Récupération des dossiers entreprises

```python
folders = sorted([p for p in ENTREPRISES_DIR.iterdir() if p.is_dir()])
```

Liste tous les sous-dossiers du répertoire `entreprises` (chaque dossier = une entreprise).

### 3.2 Traitement d’une entreprise

Pour chaque dossier :

1. **Vérification de l’existence de `page.png`**
   ```python
   page_path = folder / "page.png"
   if not page_path.exists():
       print(f"⚠️  {folder.name} → page.png manquant")
       continue
   ```

2. **Ouverture de l’image**
   ```python
   img = Image.open(page_path).convert("RGB")
   ```

3. **Calcul dynamique de `y_end`**
   ```python
   anchors = find_section_anchors(img)
   y_end = anchors.get("indicateurs_financiers", 0.40 * img.height)
   ```
   - Cherche la position verticale de la section « Indicateurs économiques et financiers ».
   - Si l’ancre n’est pas trouvée → repli sur `0.40 * hauteur` (comportement précédent) + ajout d’un avertissement dans le résultat.

4. **Extraction du Tableau 1**
   ```python
   result = extract_table1(
       img,
       y_start=0,          # extract_table1 relocalise SIGLE en interne
       y_end=y_end,
       x_frac_end=None,
   )
   ```

5. **Gestion des cas particuliers**
   - Si le sigle n’a pas été trouvé par l’OCR :
     ```python
     result["sigle"] = folder.name.split("_")[0] + " (a verifier)"
     ```
   - Ajout du nom du dossier :
     ```python
     result["_dossier"] = folder.name
     ```

6. **Sauvegarde individuelle**
   - JSON : `table1_infos_v1.json`
   - CSV : `table1_infos_v1.csv` (format champ / valeur)

### 3.3 Génération du CSV global

À la fin du traitement de toutes les entreprises :

```python
all_keys = sorted({k for row in all_results for k in row.keys()})
```

Crée un CSV unique contenant toutes les colonnes rencontrées (union des clés) et une ligne par entreprise.

---

## 4. Structure des fichiers générés

### Par entreprise (dans son dossier)
| Fichier                     | Description                          |
|----------------------------|--------------------------------------|
| `table1_infos_v1.json`     | Résultat complet au format JSON      |
| `table1_infos_v1.csv`      | Même résultat en CSV (champ / valeur)|

### Global
| Fichier                                      | Description                          |
|---------------------------------------------|--------------------------------------|
| `../output/toutes_entreprises_table1_v1.csv`| Toutes les entreprises en un seul CSV|

---

## 5. Messages de suivi

Le script affiche dans le terminal :
- Le nombre total d’entreprises trouvées
- Le nom de l’entreprise en cours de traitement
- Un résumé du nombre de champs extraits
- Les éventuelles erreurs ou avertissements (ancre non trouvée, page.png manquant, etc.)

---

## 6. Points de robustesse

| Situation                              | Comportement du script                                      |
|----------------------------------------|-------------------------------------------------------------|
| `page.png` manquant                    | Avertissement + passage à l’entreprise suivante             |
| Ancre « indicateurs_financiers » absente | Utilisation de la fraction fixe 0.40 + flag `_warning_ancre` |
| Sigle non détecté par l’OCR            | Repli sur le préfixe du nom de dossier + mention « a verifier » |
| Exception quelconque                   | Affichage de l’erreur + continuation du traitement          |

---

## 7. Limites connues

- Dépend entièrement de la qualité de `find_section_anchors` et de `extract_table1`.
- Le repli sur `0.40 * hauteur` peut encore être imprécis sur certaines pages atypiques.
- Les champs extraits dépendent de ce que renvoie `extract_table1` (pas de validation métier dans ce script).

---

## 8. Améliorations possibles

- Logger les entreprises pour lesquelles l’ancre de repli a été utilisée
- Ajouter un mode « dry-run »
- Paralléliser le traitement (multiprocessing)
- Générer un rapport de synthèse (taux de réussite, champs manquants fréquents, etc.)

---

## 9. Conclusion

Ce script constitue la couche d’orchestration qui permet de traiter en masse l’extraction du Tableau 1.  
Grâce à l’utilisation d’ancres dynamiques, il s’adapte correctement à la variabilité de hauteur du bandeau « nom d’entreprise », problème qui rendait l’ancienne approche (fraction fixe) insuffisamment fiable.
