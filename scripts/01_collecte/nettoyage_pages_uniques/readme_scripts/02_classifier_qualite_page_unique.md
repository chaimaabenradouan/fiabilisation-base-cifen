# 02_classifier_qualite_page_unique.py — Classification qualité des PDF 1 page

**Étape 2 / 3** du pipeline de nettoyage des rapports 1 page.
Emplacement dans le projet : `01_collecte/nettoyage_pages_uniques/02_classifier_qualite_page_unique.py`

## Objectif

Pour chaque PDF d'1 page repéré à l'étape 1, déterminer s'il s'agit d'un **vrai**
état financier condensé ou d'un **faux** (communiqué, page vide, scan). Réutilise
le même moteur de reconnaissance comptable (`moteur_reconnaissance_comptable_cgnc.py`)
que le moteur de localisation, pour rester cohérent avec le reste du pipeline.

## Les 5 verdicts possibles

| Verdict | Signification | Action associée |
|---|---|---|
| `OK_REEL` | Au moins 2 des 3 états (Bilan Actif / Bilan Passif / CPC) détectés avec un score suffisant + au moins 1 tableau structurel trouvé | À garder tel quel |
| `FAKE_ANNONCE` | Motif de communiqué détecté ("disponible sur le site...") **et** 0/3 état financier trouvé | À re-scraper (étape 3) |
| `SCANNE_A_VERIFIER` | Texte quasi vide (< 50 caractères normalisés) → probable scan image, injugeable par le texte | Image PNG générée pour vérification visuelle |
| `A_VERIFIER` | Signal ambigu : ni clairement faux, ni assez solide pour être sûr | Image PNG générée pour vérification visuelle |
| `ERREUR_LECTURE` | Le PDF n'a pas pu être ouvert | À investiguer manuellement |

## Utilisation

```bash
python 02_classifier_qualite_page_unique.py --input nettoyage_1page/ONEPAGE_REPORTS.csv
```

### Arguments

| Argument | Défaut | Description |
|---|---|---|
| `--input` | `nettoyage_1page/ONEPAGE_REPORTS.csv` | CSV produit par l'étape 1 |
| `--out` | `nettoyage_1page/CLASSIFICATION_1PAGE.csv` | CSV de résultat |

## Constantes de réglage

| Constante | Valeur | Rôle |
|---|---|---|
| `MIN_SCORE_CATEGORY` | 15 | Score minimum (sur le dictionnaire CGNC pondéré) pour considérer une catégorie (bilan actif/passif/CPC) comme "trouvée" |
| `MIN_CATEGORIES_REEL` | 2 | Nombre minimum de catégories trouvées parmi les 3 pour valider `OK_REEL` |
| `SEUIL_CHARS_SCANNE` | 50 | En-dessous de ce nombre de caractères normalisés, le PDF est considéré comme un scan |
| `RENDER_ZOOM` | 2.5 | Facteur de zoom (matrice PyMuPDF) pour le rendu des images de vérification |

## Logique de décision (`classify_one_pdf`)

```
Ouvrir le PDF
  → échec → ERREUR_LECTURE

Extraire le texte de la page unique, normaliser
  → si n_chars < 50 → rendre l'image PNG → SCANNE_A_VERIFIER

Détecter les tableaux structurels (page.find_tables())
Scorer le texte contre les 3 dictionnaires CGNC (bilan_actif, bilan_passif, cpc)
Scorer aussi le dictionnaire "identification" (infos légales de l'entreprise)
Détecter les motifs de communiqué (ANNOUNCEMENT_PATTERNS)

  → si motif de communiqué ET 0 catégorie trouvée → FAKE_ANNONCE
  → si ≥ 2 catégories trouvées ET ≥ 1 tableau détecté → OK_REEL
  → sinon → rendre l'image PNG → A_VERIFIER
```

## Motifs de communiqué détectés (`ANNOUNCEMENT_PATTERNS`)

Phrases normalisées (accents/apostrophes retirés) indiquant qu'il s'agit d'une
annonce renvoyant vers un site externe plutôt qu'un vrai rapport :

- "disponible sur son site internet"
- "disponible sur le site internet"
- "est aujourd hui disponible"
- "veuillez consulter notre site"
- "consultable sur le site"
- "telechargeable sur"

## Rendu des images de vérification

Pour les verdicts `SCANNE_A_VERIFIER` et `A_VERIFIER`, la page est rendue en PNG
(zoom x2.5) dans `nettoyage_1page/A_VERIFIER_VISUELLEMENT/<ENTREPRISE>_<ANNEE>.png`,
afin de permettre une vérification visuelle rapide.

## Structure du CSV de sortie (`CLASSIFICATION_1PAGE.csv`)

| Colonne | Description |
|---|---|
| `Entreprise`, `Annee`, `Chemin` | Repris de l'entrée |
| `verdict` | Un des 5 verdicts ci-dessus |
| `detail` | Phrase explicative (ex. "2/3 état(s) financier(s) + 1 tableau(x) détecté(s)") |
| `n_chars` | Nombre de caractères de texte normalisé extrait |
| `n_tables` | Nombre de tableaux structurels détectés |
| `categories_trouvees` | Liste des catégories validées (ex. `bilan_actif, cpc, identification`) |
| `image_verification` | Chemin vers le PNG généré (vide si `OK_REEL` ou `FAKE_ANNONCE`) |

Les lignes sont triées par ordre de priorité de traitement :
`FAKE_ANNONCE` → `SCANNE_A_VERIFIER` → `A_VERIFIER` → `ERREUR_LECTURE` → `OK_REEL`.

## Dépendances

- `PyMuPDF` (`fitz`)
- Module maison `moteur_reconnaissance_comptable_cgnc.py` (fonctions `normalize`,
  `score_against_category`, dictionnaire `CATEGORY_KEYWORDS`)

## Prochaine étape

➡️ Vérifier manuellement les images dans `A_VERIFIER_VISUELLEMENT/`, puis lancer
`03_rescrap_pages_uniques_fausses.py` sur les verdicts à re-scraper.
