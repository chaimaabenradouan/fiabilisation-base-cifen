# Documentation — `04_classifier_texte_vs_scanne.py` (anciennement classify_scanned_vs_text.py)

## 1. Rôle dans le pipeline

Ce script répond à une question préalable indispensable avant tout traitement automatisé des rapports : **le texte est-il extractible ou s'agit-il d'un scan (image) ?** Un "moteur de localisation" (qui cherche du texte natif dans le PDF pour repérer les tableaux Bilan/CPC) ne peut fonctionner que sur des documents dont le texte est réellement extractible. Ce script classe chaque rapport volumineux en 3 catégories, sans faire d'OCR (ce qui serait beaucoup plus lent).

## 2. Les 3 catégories

| Catégorie | Signification | Conséquence |
|---|---|---|
| **TEXTE** | Texte extractible sur la quasi-totalité des pages | Le moteur de localisation peut travailler directement dessus |
| **SCANNE** | Quasi aucun texte extractible (image pure) | Nécessite un traitement OCR, hors scope pour l'instant |
| **MIXTE** | Une partie scannée, une autre non (ex. annexes scannées mais états financiers en texte natif) | À traiter au cas par cas |

## 3. Méthode de classification

Pour chaque page du PDF (via PyMuPDF) :
- Le texte est extrait (`page.get_text()`).
- Si le nombre de caractères extraits est **inférieur à `SEUIL_CHARS_PAGE_VIDE` (50)**, la page est considérée "quasi vide" en texte (probablement une image).

Sur l'ensemble du document, on calcule le **pourcentage de pages "vides"** (`pct_pages_vides`), puis :

- `pct_pages_vides >= 85 %` (`SEUIL_PCT_SCANNE`) → **SCANNE**
- `pct_pages_vides <= 15 %` (`SEUIL_PCT_TEXTE`) → **TEXTE**
- Entre les deux → **MIXTE**

Cette approche est **rapide** (pas d'OCR, juste extraction de texte natif via PyMuPDF), même sur des documents de 300+ pages.

## 4. Deux modes d'utilisation

### Mode batch (via JSON)
Traite tous les rapports listés dans un fichier `rapports_volumineux.json` (celui généré par `detect_volumineux_from_json.py`), en résolvant automatiquement le chemin de chaque PDF via `--rapports-dir`.

### Mode test unitaire (`--pdf`)
Permet de tester la classification sur un seul fichier PDF, en déduisant l'entreprise et l'année à partir du chemin du fichier (nom du dossier parent = entreprise, nom du fichier sans extension = année).

## 5. Utilisation

```bash
# Sur tous les rapports d'un JSON
python classify_scanned_vs_text.py --json rapports_volumineux.json --seuil-pages 100

# Test sur un seul fichier
python classify_scanned_vs_text.py --pdf "Rapports/MANAGEM/2018.pdf"
```

| Argument | Description | Défaut |
|---|---|---|
| `--json` | Chemin du JSON des rapports volumineux | Aucun |
| `--pdf` | Tester sur un seul PDF au lieu d'un JSON complet | Aucun |
| `--rapports-dir` | Dossier contenant les PDF | `Rapports` |
| `--seuil-pages` | Ne traiter que les rapports au-delà de ce nombre de pages (0 = tous) | `0` |
| `--out` | Fichier CSV de sortie | `smart_test_output/CLASSIFICATION_SCAN_TEXTE.csv` |

Note : `--json` et `--pdf` sont mutuellement exclusifs dans l'usage (l'un des deux doit être fourni, sinon le script affiche une erreur et s'arrête).

## 6. Sortie produite

**`smart_test_output/CLASSIFICATION_SCAN_TEXTE.csv`**, avec les colonnes :

| Colonne | Description |
|---|---|
| `Entreprise` | Nom de l'entreprise |
| `Annee` | Année du rapport |
| `Chemin` | Chemin du fichier PDF analysé |
| `n_pages` | Nombre total de pages |
| `pct_pages_vides` | % de pages considérées "vides" en texte |
| `chars_par_page_moyen` | Nombre moyen de caractères extraits par page |
| `classification` | `TEXTE` / `SCANNE` / `MIXTE` / `ERREUR_LECTURE` / `FICHIER_INTROUVABLE` |
| `detail` | Détail de l'erreur, le cas échéant |

Un résumé chiffré (nombre de documents par catégorie) est également affiché en console à la fin de l'exécution.

## 7. Limites connues

- Le seuil de 50 caractères pour considérer une page "vide" est arbitraire ; une page contenant très peu de texte réel (ex. une page de garde) pourrait être classée à tort comme "scannée" si elle est isolée, mais cela a peu d'impact car c'est le **pourcentage global** sur tout le document qui détermine la classification finale.
- Les catégories `SCANNE` ne bénéficient d'aucun traitement automatique dans ce pipeline (l'OCR est explicitement hors scope) ; elles nécessitent un traitement manuel ou un futur script dédié.
- La catégorie `MIXTE` n'est pas subdivisée plus finement (on ne sait pas *quelles* pages sont scannées) — un examen manuel reste nécessaire pour ces cas.
