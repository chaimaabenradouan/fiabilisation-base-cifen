# `extract_table3.py` — Immobilisations corporelles (grille 2×2)

Ce tableau a une structure différente des deux précédents : ce n'est pas une liste verticale mais une **grille fixe 2×2** :

```
Terrains                Constructions
Installations tech.     Mobilier, Mat. bureau
```

Chaque case contient un libellé avec sa valeur juste en dessous (jamais au-dessus, jamais loin).

## Étape 1 — localiser les 4 libellés

Recherche par mot-clé tolérant (`FIELD_KEYWORDS`), un seul mot distinctif suffit ("terrains", "constructions", "installations", "mobilier"). Le dictionnaire prévoit aussi des variantes observées chez certaines institutions financières (CAM, CDG) où deux cases sont fusionnées visuellement en une seule (ex. "Terrain & construct." → `terrain_construction`, "Equip. Mobilier & Inst." → `equip_mobilier_inst`), ou des variantes sectorielles (ONCF : "matériel de transport" plutôt que "mobilier de bureau"), ainsi que des catégories additionnelles (`droit_utilisation_location`, `logiciel_acquis`).

L'ordre du dictionnaire `FIELD_KEYWORDS` compte : les mots-clés les plus spécifiques sont testés en priorité, pour éviter qu'un mot-clé court (ex. "construct" pour la variante bancaire fusionnée) ne vole aussi le mot standard complet "Constructions" déjà revendiqué par le champ standard.

## Un bug corrigé : doublon sur les bannières fusionnées

Sur CAM, le mot "Mobilier" à l'intérieur de la bannière fusionnée "Equip. Mobilier & Inst." matchait *aussi* le mot-clé du champ standalone `mobilier_mat_bureau`, créant un second libellé fantôme presque à la même position. Le mauvais chiffre pouvait alors être associé au mauvais libellé (observé : la vraie valeur de `equip_mobilier_inst` collée à `mobilier_mat_bureau`, et une valeur d'un graphique voisin collée à `equip_mobilier_inst`).

**Correctif** : si deux libellés sont détectés quasiment au même endroit (même ligne, moins de 20px d'écart vertical et moins de 400px d'écart horizontal), c'est le signe d'une bannière mal scindée en deux — le doublon `mobilier_mat_bureau` est supprimé et seul `equip_mobilier_inst` est conservé. Ne s'applique jamais aux entreprises standard, où `equip_mobilier_inst` n'existe pas du tout.

## Une inférence géométrique

Constat récurrent sur toutes les entreprises testées : le mot "Constructions" est presque systématiquement raté par l'OCR (cause non identifiée, pas un bug de logique). Comme la grille standard est fixe, si les 2 libellés de la ligne du bas (`installations_tech`, `mobilier_mat_bureau`) sont trouvés mais un seul des 2 de la ligne du haut, on déduit la position du libellé manquant **par symétrie de grille** : même décalage horizontal (dx) que la ligne du bas, même hauteur (y) que le libellé trouvé de la ligne du haut. Purement géométrique — aucune valeur d'entreprise codée en dur — et ne s'applique qu'au motif standard 4-champs, jamais aux variantes bancaires fusionnées.

## Étape 2 — nettoyage des nombres

`_clean_number` gère une particularité propre à ce tableau : le séparateur observé est un **point tous les 3 chiffres** (ex. "16.102" = 16 102, et non 16,102 en décimal), car aucune décimale n'a été observée dans ce tableau spécifique — différent des tableaux 1 et 2. Un tiret isolé ("-", "—", "–") est traité comme une valeur nulle/absente, laissée vide plutôt que remplacée par un faux zéro (pour que l'absence de donnée reste visible).

## Étape 3 — assignation nombre → libellé, en 1-pour-1

**Ancienne approche** : chaque nombre choisissait indépendamment son libellé le plus proche en dessous. Bug observé : si un libellé n'était pas détecté, deux valeurs différentes pouvaient revendiquer le même libellé et se retrouver collées en un seul nombre absurde (ex. "2.576" + "6.153" → "2.5766153").

**Nouvelle approche** : on construit toutes les paires valides (nombre, libellé) avec un score de distance (`score = dy + dx * 0.3`, priorité à la distance verticale, tolérance horizontale), on trie ces paires par score croissant, puis on assigne en mode glouton en interdisant de réutiliser un nombre ou un libellé déjà pris. Un nombre qui ne trouve aucun libellé disponible reste ignoré : une case vide est préférable à une valeur fusionnée à tort.

## Fonction principale : `extract_table3(img, y_start, y_end, x_frac_start=0.0, x_frac_end=1.0)`

Combine toutes les étapes ci-dessus (localisation des libellés, dédoublonnage, inférence géométrique, nettoyage et assignation des nombres) et retourne un dictionnaire `{champ: valeur}`, plus un indicateur de diagnostic `_diag_avg_score` (score moyen des assignations retenues) qui sert en amont, dans le script d'orchestration `run_all_table3.py` (non fourni ici), à choisir la meilleure passe parmi plusieurs tentatives.

Le script contient aussi de nombreux `print()` de debug (mots OCR bruts, libellés trouvés, distances calculées) qui facilitent le diagnostic entreprise par entreprise sans avoir à republier tout le log.
