# `extract_table1.py` — Informations de base (Sigle, capital, classification…)

Ce script extrait les champs du premier tableau : sigle, capital social, date de création, classification juridique, activité, catégorie, et les 3 taux de participation (totale, directe, indirecte).

## Principe : lire le texte, jamais forcer une valeur

Contrairement à une ancienne version qui utilisait des listes de valeurs autorisées comme filtre strict ("whitelist"), cette version affiche **toujours le texte réellement lu par l'OCR**. Les listes `KNOWN_CLASSIFICATIONS` et `KNOWN_CATEGORIES` ne servent plus qu'à une correction orthographique optionnelle (distance de Levenshtein) : si le texte lu est très proche d'une valeur connue du formulaire (ex. faute OCR sur "FILIALE PUBLIQUE"), on corrige ; sinon, on garde le texte brut tel quel plutôt que de risquer une correction erronée invisible. Le champ `activite` est explicitement exclu de cette correction car c'est du texte libre, pas une valeur fermée du formulaire.

## Repérage des champs (`FIELD_KEYWORDS`)

Pour chaque champ, un mot-clé sert d'ancre (ex. "sigle", "capital"+"social", "categorie"…). Une fois tous les libellés localisés sur la page, `_single_pass` calcule pour chaque champ une **bande verticale** délimitée par le libellé précédent et le suivant (avec une hauteur maximale `MAX_BAND_HALF_HEIGHT` pour éviter qu'une bande ne déborde trop), et récupère tous les mots qui tombent dans cette bande — en excluant les mots du libellé lui-même et les mots de bruit comme "millions", "dh" (voir `NOISE_WORDS`).

## Cas particulier : le sigle

Le sigle est traité à part car sa case est en haut de page, dans une zone d'en-tête plus complexe. Trois tentatives successives, dans l'ordre :

1. Une passe standard (`_single_pass`) sur plusieurs largeurs de recadrage (`CROP_WIDTHS`).
2. Si vide, une passe de repli dédiée (`_sigle_fallback_pass`) qui relocalise précisément le mot "sigle" puis relit juste en dessous.
3. Si toujours vide, une extraction "manuelle" (`_extract_sigle_dedicated`) qui cherche le mot "sigle" et prend tout ce qui est sur la même ligne, juste après.

Le nettoyage (`_clean_sigle`) s'arrête dès qu'il rencontre un mot d'arrêt (`SIGLE_STOP`, ex. "maison", "groupe") pour éviter de capter le nom complet de l'entreprise à la suite du sigle.

## Nettoyage des autres champs

- **`_clean_text_field`** : retire les mots de bruit (unités, libellés de champs mal isolés), les tokens "poubelle" (`_is_garbage_token` : trop longs, ou avec une lettre répétée 5 fois de suite = artefact OCR), et les résidus arabes mal filtrés (`_looks_like_arabic_bleed`).
- **`_extract_date`** : cherche un motif `JJ/MM/AAAA` (ou variantes à 2/3 chiffres pour l'année) et valide que la date est plausible (jour ≤31, mois ≤12, année entre 1900 et 2030).
- **`_merge_capital_spaces`** puis **`_best_capital`** : recolle les espaces de séparateur de milliers français (ex. "2 104,0" → "2104,0"), garde le plus long nombre candidat trouvé dans le texte, puis le reformate proprement avec des espaces tous les 3 chiffres.
- Les 3 champs de participation sont recherchés comme un motif `xx,x %` et on garde la valeur la plus fréquente entre les différentes passes (largeurs de recadrage).

## Fonction principale : `extract_table1(img, y_start, y_end, x_frac_end=None)`

Elle lance plusieurs passes à différentes largeurs de recadrage (`CROP_WIDTHS = [0.58, 0.72, 0.85]`), et pour chaque champ garde la première valeur non vide trouvée (sigle, activité, classification, catégorie), la date/le capital les plus complets/fréquents, ou le pourcentage le plus fréquent (participations). C'est une stratégie de vote/repli qui compense l'instabilité de l'OCR d'une passe à l'autre : si une largeur de recadrage rate un champ, une autre largeur a de bonnes chances de le récupérer.
