# `anchors.py` — repérer les 3 sections sur la page

Ce script répond à une question simple : **à quelle hauteur (coordonnée Y) commence chaque section** (Informations de base, Indicateurs financiers, Gouvernance, Indicateurs d'activité, Immobilisations corporelles) sur la page scannée ? Ces coordonnées servent ensuite de repères pour découper les zones à passer aux 3 extracteurs (`extract_table1.py`, `extract_table2.py`, `extract_table3.py`).

## Logique générale

`SECTION_ANCHORS` est une liste de `(nom_de_section, [mots-clés])`. Pour chaque section, on cherche dans les lignes OCR celle qui contient le plus de mots-clés correspondants. La fonction `find_section_anchors` fait plusieurs passages OCR à différentes échelles d'agrandissement (`UPSCALES = [1.8, 1.4, 2.2]`) : si une ancre n'est pas trouvée à la première échelle, on retente avec la suivante, jusqu'à toutes les trouver ou épuiser la liste.

## Les deux bugs corrigés (documentés en tête de fichier)

### Fix 1 — le bandeau-titre n'est pas toujours écrit pareil

Sur certaines entreprises (ADM), la section s'appelle "Informations de base", sur d'autres (CDG, OFPPT) "Informations Générales". Le script cherchait à l'origine les 2 mots-clés "informations" + "base" : sur les pages où c'est écrit "Générales", le mot "base" n'existe nulle part, l'ancre n'était donc jamais trouvée avec assez de confiance, ce qui faisait démarrer la zone de recherche trop haut, capturant le bandeau du nom de l'entreprise au lieu de la case "Sigle".

→ **Solution** : ne garder que le mot "informations" seul, qui est commun aux deux variantes et n'apparaît nulle part ailleurs sur la page.

### Fix 2 / 2bis — une règle de tolérance trop générale créait une ambiguïté, puis une régression en la corrigeant

La règle d'origine acceptait qu'un mot-clé manque sur deux (`min_hits = max(1, len(mots_clés) - 1)`). Problème concret : pour `indicateurs_activite = ["indicateurs", "activite"]` (2 mots), cette règle autorisait à ne matcher que sur le seul mot "indicateurs" — qui est aussi le premier mot-clé de `indicateurs_financiers`. Résultat : une ligne "Indicateurs économiques et financiers" mal reconnue pouvait déclencher les deux ancres en même temps, sur la même ligne, silencieusement.

Le premier correctif (**Fix 2**) a donc décidé d'exiger tous les mots-clés pour toute liste de 2 mots ou moins. Mais cette règle, appliquée trop largement, a aussi durci `immo_corporelles` (2 mots-clés : "immo", "corporelles") — qui n'avait rien à voir avec le problème initial. Résultat observé sur un run réel : dès que l'OCR ratait le mot "corporelles" (fréquent, mot long), l'ancre ne se déclenchait plus jamais.

Le correctif final (**Fix 2bis**) restreint donc l'exigence stricte à la **seule** ancre réellement ambiguë (`indicateurs_activite`) ; toutes les autres, `immo_corporelles` incluse, gardent la tolérance d'origine (1 mot manquant accepté).

## Les fonctions

### `_find_in_pass(lines, name, keywords)`
Applique la règle de tolérance décrite ci-dessus (stricte pour `indicateurs_activite`, tolérante à 1 mot manquant pour toutes les autres ancres) et retourne la coordonnée Y (centre vertical) de la meilleure ligne trouvée, ou `None` si le score minimal n'est pas atteint.

### `find_section_anchors(img, x_range=(0, 0.72))`
Boucle sur les échelles d'agrandissement (`UPSCALES`), relance l'OCR sur la zone `x_range` de la page à chaque échelle, et tente de localiser chaque ancre encore manquante via `_find_in_pass`. Retourne un dictionnaire `{nom_section: y}` avec toutes les ancres trouvées.
