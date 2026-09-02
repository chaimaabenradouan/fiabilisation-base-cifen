# `extract_table2.py` — Indicateurs financiers (v3, canonicalisation)

Ce script lit le deuxième tableau : une liste de lignes financières (chiffre d'affaires, résultat net, effectif…) réparties sur plusieurs colonnes (généralement 3 années).

## Le changement de stratégie (v3)

Les versions précédentes transformaient directement le texte OCR brut en nom de colonne ("slugification"). Problème : un seul mot arabe mal reconnu en charabia latin se retrouvait collé au nom du champ (exemple cité en commentaire : `charges_d_exploitation_hd_euaosiall_cu`).

La v3 utilise à la place une **liste blanche d'environ 15 champs connus** (`CANONICAL_FIELDS`), observés sur les 19 entreprises testées. Chaque ligne du tableau est comparée à ces motifs par mots-clés (tous les mots du motif doivent apparaître, dans n'importe quel ordre, avec d'autres mots autour tolérés). Dès qu'un motif matche, on utilise directement le nom canonique fixe — tout le charabia OCR autour (mots arabes mal reconnus, bruit) est simplement ignoré, jamais concaténé. Une ligne qui ne matche aucun motif connu est ignorée (et affichée dans les logs, `print(...)`, pour transparence), plutôt que de créer une colonne bruit.

## Détection de la ligne d'en-tête (par structure, pas par texte)

Au lieu de chercher le mot "Indicateurs" dans le texte (qui peut être mal reconnu en "imticateurs" par exemple, et raterait un test de sous-chaîne), `_looks_like_year_tokens` regarde si au moins la moitié des tokens numériques d'une ligne ressemblent à une année (19xx/20xx). C'est plus fiable car indépendant de la qualité de lecture du texte du libellé.

## Les colonnes (années)

`_cluster_columns` regroupe les positions X des nombres en colonnes, en coupant aux plus grands écarts horizontaux entre positions triées (méthode par plus grands "gaps"), puis affine ce découpage par quelques itérations de type k-means simplifié.

Point important : `_guess_year_labels` **n'essaie plus de lire les vraies années** (2022/2023/2024) depuis l'en-tête, car cette lecture était instable d'une page à l'autre (parfois lue, parfois non) et produisait deux schémas de nommage différents selon les entreprises dans le même fichier CSV final (ex. `..._2023` pour l'une, `..._annee_2` pour l'autre — illisible et non comparable). À la place, on utilise systématiquement des labels génériques `annee_1`, `annee_2`, `annee_3` pour toutes les entreprises, garantissant un schéma unique et comparable. Une tâche reste notée en commentaire dans le code : vérifier manuellement, sur 1-2 entreprises connues, à quelle vraie année correspond chaque label générique, et documenter la correspondance.

## Sous-sections (cas CNSS)

`SECTION_HEADER_WHITELIST` gère un cas particulier où le tableau contient des sous-titres ("Régime général", "Assurance maladie", "AMO") qui préfixent alors le nom du champ (ex. `regime_general_cotisations_contributions`), via `_is_section_header`.

## Fonction principale : `extract_table2(img, y_start, y_end, x_frac_end=0.75, n_cols=3)`

Parcourt les lignes OCR (`cluster_lines`), sépare mots textuels (libellé) et tokens numériques, détecte l'en-tête (`_looks_like_year_tokens`), associe chaque ligne à un champ canonique via `_canonical_field`, assigne chaque nombre à sa colonne la plus proche (`nearest_col`), et construit un dictionnaire `{nom_champ_annee: valeur}`. Gère aussi les doublons de libellé (ex. deux lignes "Résultat net" dans des sections différentes) en suffixant `_dup2`, `_dup3`, etc.
