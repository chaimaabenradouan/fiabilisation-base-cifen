# `ocr_utils.py` — la boîte à outils OCR commune

C'est le socle technique utilisé par les 3 scripts d'extraction (`extract_table1.py`, `extract_table2.py`, `extract_table3.py`). Il ne contient aucune logique métier (pas de noms de champs, pas de mots-clés) : juste des fonctions génériques de bas niveau.

## Pourquoi Tesseract, et pas un modèle "table structure recognition" ?

Le commentaire d'en-tête explique le choix : des outils comme Docling ou Table Transformer attendent une vraie grille avec des bordures nettes (comme un tableau Excel imprimé). Or la fiche EEP est un **formulaire** : les cases label/valeur sont fusionnées visuellement, un libellé peut s'étaler sur 1 à 3 lignes, et une colonne en arabe est collée juste à côté. Ces modèles auraient tendance à casser ou fusionner les champs n'importe comment.

La solution retenue est donc plus artisanale mais plus robuste : OCR mot par mot avec coordonnées, puis **ancrage par mot-clé** (on repère où se trouve un libellé connu, et on regarde ce qu'il y a juste à droite ou en dessous). C'est ce principe que les 4 fonctions ci-dessous mettent en œuvre.

## Les 4 fonctions

### `normalize(text)`
Met en minuscules, retire les accents, nettoie les espaces multiples. Sert à comparer un mot lu par l'OCR à un mot-clé de référence sans se soucier de la casse ou des accents (ex. "Créé" et "cree" doivent matcher).

### `strip_arabic(text)`
Enlève les caractères arabes qui auraient "bavé" dans la zone française à cause d'un recadrage un peu trop large (la fiche a une colonne arabe juxtaposée à la colonne française).

### `ocr_words(img, box, upscale, psm, lang)`
La fonction centrale, utilisée par tous les autres scripts. Elle :
1. Découpe une zone rectangulaire (`box`) de l'image pleine page.
2. La convertit en niveaux de gris.
3. L'agrandit (`upscale`, par défaut x1.5 — un compromis : suffisant pour que Tesseract lise correctement les petits chiffres, sans être si gros que le seuillage interne de Tesseract commence à abîmer l'anti-aliasing).
4. Lance Tesseract dessus en mode `psm=11` (texte épars, ordre de lecture non garanti — le mode le plus robuste pour un formulaire où le texte est dispersé dans des cases, pas dans un flux de paragraphe classique).

Elle retourne une liste de mots (dicts `{left, top, width, height, text}`) en coordonnées **absolues**, c'est-à-dire relatives à l'image originale et non au recadrage. Ce choix permet de comparer ou combiner facilement les résultats de plusieurs appels sans se perdre entre plusieurs systèmes de coordonnées.

### `cluster_lines(words, y_tolerance=12)`
Regroupe une liste de mots individuels en "lignes visuelles", en comparant leur centre vertical. Deux mots dont le centre vertical diffère de moins de `y_tolerance` pixels sont considérés comme sur la même ligne. Utile pour reconstituer un libellé écrit sur plusieurs mots, ou une ligne de tableau. Retourne une liste de lignes triées de haut en bas, chaque ligne étant elle-même triée de gauche à droite.

### `line_text(line)`
Concatène le texte de tous les mots d'une ligne (après nettoyage des résidus arabes) en une seule chaîne de caractères.
