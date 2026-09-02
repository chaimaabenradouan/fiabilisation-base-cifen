# moteur_reconnaissance_comptable_cgnc.py — Moteur de reconnaissance comptable CGNC

Module partagé, importé par `02_classifier_qualite_page_unique.py` et
`03_rescrap_pages_uniques_fausses.py` (`from moteur_reconnaissance_comptable_cgnc
import normalize, score_against_category, CATEGORY_KEYWORDS`).


## Rôle

Fournit le référentiel de mots-clés comptables **CGNC** (Code Général de la
Normalisation Comptable marocain) et les fonctions de scoring textuel utilisées
dans tout le pipeline pour reconnaître :

- les infos d'**identification** de l'entreprise,
- le **Bilan Actif**,
- le **Bilan Passif**,
- le **CPC** (Compte de Produits et Charges).

## Dictionnaires de mots-clés pondérés

| Dictionnaire | Contenu |
|---|---|
| `KEYWORDS_IDENTIFICATION` | Raison sociale, RC, ICE, siège social, forme juridique, capital social, patente, CNSS... |
| `KEYWORDS_BILAN_ACTIF` | Actif immobilisé, immobilisations (non-valeur/incorporelles/corporelles/financières), actif circulant, trésorerie actif, total actif, stocks, créances... |
| `KEYWORDS_BILAN_PASSIF` | Capitaux propres, dettes de financement, provisions durables, passif circulant, trésorerie passif, total passif, fournisseurs, résultat net de l'exercice... |
| `KEYWORDS_CPC` | Chiffre d'affaires, produits/charges d'exploitation, résultat d'exploitation/financier/courant/non courant, impôts sur les résultats, résultat net... |

Chaque mot-clé est associé à un **poids** (int) reflétant sa spécificité : par
exemple `"total actif"` pèse 26 (très discriminant) alors que `"actif"` seul ne
pèse que 4 (trop générique, présent presque partout).

Ces 4 dictionnaires sont regroupés dans :

```python
CATEGORY_KEYWORDS = {
    "identification": KEYWORDS_IDENTIFICATION,
    "bilan_actif": KEYWORDS_BILAN_ACTIF,
    "bilan_passif": KEYWORDS_BILAN_PASSIF,
    "cpc": KEYWORDS_CPC,
}
```

## Fonctions principales

### `normalize(text: str) -> str`

Normalise un texte pour le rendre comparable indépendamment des accents, de la
casse et de la ponctuation :

1. Décomposition Unicode NFKD (sépare les accents des lettres).
2. Suppression des marques diacritiques (accents).
3. Passage en minuscules + suppression de tout caractère non alphanumérique.
4. Compression des espaces multiples.

Exemple : `"Chiffre d'Affaires !"` → `"chiffre d affaires"`.

### `fuzzy_contains(keyword_norm, text_norm, threshold=0.78, use_fuzzy=True) -> bool`

Vérifie si un mot-clé est présent dans un texte, avec **tolérance aux erreurs
OCR / polices corrompues** :

1. D'abord un test d'inclusion exacte (rapide) : `keyword_norm in text_norm`.
2. Si `use_fuzzy=False` ou le mot-clé n'est pas trouvé exactement et que le
   flou est désactivé → renvoie `False`.
3. Sinon, fait glisser une fenêtre de la taille du mot-clé sur tout le texte
   (pas de `step = klen // 4` pour limiter le coût), et compare chaque fenêtre
   au mot-clé avec `difflib.SequenceMatcher`.
   - `quick_ratio()` sert de filtre rapide (majorant) avant le calcul plus
     coûteux de `ratio()`.
   - Si `ratio() >= threshold` (0.78 par défaut), le mot-clé est considéré comme trouvé.

Ce mécanisme permet de reconnaître des mots-clés même sur des PDF à police
corrompue (ex. "chiEEre" au lieu de "chiffre").

### `score_against_category(text, keywords, use_fuzzy=True) -> tuple[int, list[str]]`

Normalise le texte puis, pour chaque mot-clé du dictionnaire fourni, vérifie sa
présence via `fuzzy_contains`. Additionne les poids des mots-clés trouvés
(plafonné à 100) et renvoie `(score, liste_des_mots_clés_matchés)`.

C'est la fonction utilisée partout dans le pipeline (étapes 2 et 3) pour décider
si une page/un tableau/un document correspond à une catégorie comptable donnée.

## Utilisation typique

```python
from moteur_reconnaissance_comptable_cgnc import normalize, score_against_category, CATEGORY_KEYWORDS

score, matched = score_against_category(page_text, CATEGORY_KEYWORDS["bilan_actif"], use_fuzzy=False)
if score >= 15:
    print("Bilan actif probablement présent :", matched)
```

## Dépendances

- `difflib` (stdlib)
- `re`, `unicodedata` (stdlib)

---

## Annexe — Moteur de localisation (`FinancialStatementLocalizationEngineV2`)

Si cette classe vit bien dans le même fichier chez toi, voici son rôle en résumé
(à séparer dans sa propre fiche `localization_engine_v2.md` si tu préfères
garder les deux fichiers distincts) :

- **But** : pour un PDF long (rapport complet), localiser automatiquement les
  bbox (rectangles) des tableaux Bilan Actif / Bilan Passif / CPC / bloc
  d'identification, afin de les découper en images pour un traitement OCR/IA
  en aval (MinerU).
- **Correctif clé vs v1** : la v1 cherchait le **titre** exact du tableau
  (`page.search_for("BILAN ACTIF")`), ce qui échouait sur les polices
  corrompues et retombait sur un bbox "presque toute la page". La v2 détecte
  d'abord la **structure réelle des tableaux** (`page.find_tables()`, basé sur
  les lignes/grilles du PDF, insensible à la police), puis score le texte de
  chaque tableau détecté pour l'assigner à la bonne catégorie. Le bbox retenu
  est donc toujours celui d'un tableau réellement détecté.
- **Détection de corruption de police** : sonde rapide et exacte sur 5 termes
  courants (`bilan`, `actif`, `passif`, `total`, `resultat`) dans les 15
  premières pages ; si moins de 3 apparaissent tels quels, active le matching
  flou pour tout le document.
- **Détection de variante** (social vs consolidé) par page, via des marqueurs
  dédiés (`SOCIAL_MARKERS` / `CONSOLIDATED_MARKERS`).
- **Affinage ligne par ligne** (`_refine_bbox_to_matching_rows`) : quand un
  tableau détecté fusionne plusieurs états financiers (ex. Actif + Passif côte
  à côte), le bbox est restreint aux seules lignes qui matchent la catégorie
  visée.
- **Sortie** : un fichier `<pdf_stem>_localization.json` par PDF traité,
  contenant pour chaque élément localisé : pages, bbox, score, confiance,
  méthode de détection (`table_detectee` / `table_detectee_affinee` /
  `page_entiere_fallback`...), mots-clés matchés.
- **Option `--render-crops`** : sauvegarde en plus un PNG découpé par élément
  localisé, pour vérification visuelle rapide.

### Utilisation

```bash
python localization_engine_v2.py --pdf "Rapports/MANAGEM/2018.pdf"
python localization_engine_v2.py --pdf "Rapports/MANAGEM/2018.pdf" --variant consolide
python localization_engine_v2.py --pdf "Rapports/MANAGEM/2018.pdf" --render-crops
```
