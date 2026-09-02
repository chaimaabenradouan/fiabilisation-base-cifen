# Documentation du script `03_extraire_table3.py`

**Objectif** : Parcourir toutes les entreprises et extraire le **Tableau 3** (Immobilisations corporelles), en utilisant des ancres dynamiques et une stratégie de sélection intelligente parmi plusieurs largeurs de boîte d’extraction.

---

## 1. Présentation générale

Ce script constitue la troisième étape de la chaîne d’extraction. Il s’occupe exclusivement du **Tableau 3 – Immobilisations corporelles**.

Particularités importantes :
- Le Tableau 3 se trouve souvent **côte à côte** avec le panneau « Indicateurs d’activité ».
- Certaines entreprises (notamment les banques : CAM, CDG) ont une mise en page à 3 colonnes, ce qui complique le cadrage horizontal.
- Pour gérer ces variations, le script teste **plusieurs largeurs candidates** et sélectionne la meilleure grâce à un score de confiance géométrique.

---

## 2. Dépendances et chemins

```python
from projet_2.scripts.lib.extract_table3 import extract_table3
from projet_2.scripts.lib.anchors import find_section_anchors
```

**Chemins utilisés** :
- Dossier source : `../entreprises`
- Fichier de sortie global : `../output/toutes_entreprises_table3_v1.csv`

---

## 3. Stratégie de sélection des largeurs (point clé)

### 3.1 Problème rencontré (bug HAO)

L’ancienne logique « **la passe qui trouve le plus de champs gagne** » était incorrecte.  
Sur HAO, la passe large (`x_frac_start=0.35`) trouvait 4 « champs », mais 3 d’entre eux étaient en réalité des valeurs du graphique voisin « TITRES FONCIERS CRÉÉS », capturées par erreur.

### 3.2 Nouvelle logique (corrective)

Le script teste deux largeurs candidates :

```python
X_FRAC_START_CANDIDATES = [0.60, 0.35]
```

Pour chaque largeur, `extract_table3` calcule un score de confiance géométrique :

- `_diag_avg_score` = distance moyenne entre les valeurs et leurs libellés
- **Score bas = extraction fiable**
- **Score élevé = probable bruit / pollution**

**Règle de sélection finale** :
1. On ne garde que les passes qui ont trouvé **au moins 1 champ**.
2. Parmi celles-ci, on retient la passe qui a le **plus grand nombre de champs**.
3. **À égalité de nombre de champs**, on préfère la boîte **la plus étroite** (`x_frac_start` le plus grand), car elle a moins de risque de mordre sur un graphique voisin.

Cette logique a été introduite pour corriger le bug observé sur HAO et ONCF.

---

## 4. Fonctionnement détaillé

### 4.1 Option `--only`

Le script accepte un argument en ligne de commande :

```bash
python 03_extraire_table3.py --only CAM CMR HAO ONMT
```

- Sans `--only` → traite toutes les entreprises.
- Avec `--only` → ne traite que les dossiers dont le nom contient l’une des chaînes fournies.
- Le CSV de sortie est alors suffixé (`..._ONLY_CAM_CMR_HAO_ONMT.csv`).

### 4.2 Traitement d’une entreprise

1. Vérification de l’existence de `page.png`
2. Ouverture de l’image
3. Calcul dynamique de `y_start` :
   ```python
   y_start = anchors.get("immo_corporelles", 0.76 * img.height)
   y_end = img.height          # jusqu’en bas de page
   ```
4. Appel de `_extract_best_pass()` qui teste les deux largeurs et sélectionne la meilleure
5. Ajout éventuel d’un avertissement si l’ancre était absente
6. Sauvegarde JSON + CSV individuels

### 4.3 Génération du CSV global

Même principe que les scripts précédents : union de toutes les colonnes rencontrées.

---

## 5. Fichiers générés

### Par entreprise
| Fichier                              | Description                              |
|-------------------------------------|------------------------------------------|
| `table3_immo_corporelles_v1.json`   | Résultat complet au format JSON          |
| `table3_immo_corporelles_v1.csv`    | Même résultat en CSV (champ / valeur)    |

### Global
| Fichier                                              | Description                                      |
|-----------------------------------------------------|--------------------------------------------------|
| `toutes_entreprises_table3_v1.csv`                  | Toutes les entreprises                           |
| `toutes_entreprises_table3_v1_ONLY_XXX.csv`         | Version filtrée (si `--only` a été utilisé)      |

---

## 6. Messages de suivi

Le script affiche pour chaque entreprise :
- Les essais de largeur effectués
- Le nombre de champs et le score de chaque passe
- La largeur finalement retenue
- Le nombre de champs extraits

Exemple de sortie :
```
→ Traitement : HAO_GROUPE
      (essai x_frac_start=0.60)
      (bilan largeur=0.60 : 3 champ(s), score=12.4)
      (essai x_frac_start=0.35)
      (bilan largeur=0.35 : 4 champ(s), score=45.8)
      (retenu: x_frac_start=0.60 avec 3 champ(s), score=12.4)
   ✅ 3 champs extraits
```

---

## 7. Points de robustesse

| Situation                                      | Comportement                                              |
|-----------------------------------------------|-----------------------------------------------------------|
| `page.png` manquant                           | Avertissement + passage à l’entreprise suivante           |
| Ancre « immo_corporelles » absente            | Repli sur 0.76 × hauteur + flag `_warning_ancre`          |
| Aucune passe ne trouve de champ               | Retourne un dictionnaire vide                             |
| Exception quelconque                          | Affichage de l’erreur + continuation                      |
| Option `--only` avec aucun match              | Message d’erreur + arrêt propre                           |

---

## 8. Place dans la chaîne de traitement

```
01_extraire_table1.py
02_extraire_table2.py
03_extraire_table3.py          ← ce script
04_fusionner_table1_table2.py
05_fusionner_table3_final.py
06_valider_donnees_financieres.py
```

---

## 9. Limites connues

- Dépend de la qualité du score géométrique calculé par `extract_table3`.
- Les deux largeurs candidates (0.60 et 0.35) ont été choisies empiriquement ; d’autres mises en page extrêmes pourraient nécessiter d’autres valeurs.
- Aucune validation métier des valeurs extraites (laissée au script 06).

---

## 10. Conclusion

Le script `03_extraire_table3.py` est le plus sophistiqué des trois scripts d’extraction.  
Il combine :
- des ancres dynamiques verticales,
- un test de plusieurs largeurs horizontales,
- une sélection basée sur un score de confiance géométrique plutôt que sur le simple nombre de champs.

Cette approche a permis de corriger un bug important observé sur certaines entreprises (HAO, ONCF) où la passe la plus « productive » était en réalité la plus polluée.
