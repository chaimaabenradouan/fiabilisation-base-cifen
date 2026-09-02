# CIFEN — Projet de Fiabilisation des Données Financières

**Extraction • Structuration • Contrôle • Validation des données financières**
*Des données fiables pour des analyses financières fiables.*

Projet réalisé pour le **MTPME**, alimentant la base **CIFEN** (base de données
financières des entreprises marocaines), à partir de deux populations
d'entreprises :

- **65 entreprises cotées** à la Bourse de Casablanca
- **19 Établissements et Entreprises Publiques (EEP)**

---

## Chiffres clés

| Indicateur | Valeur |
|---|---|
| Entreprises traitées (Bourse) | 65 |
| Établissements et Entreprises Publiques (EEP) | 19 |
| États financiers extraits | 1 578 |
| Rapports analysés | 526 |
| Période couverte | 2016 – 2025 |
| **Taux de fiabilisation global** | **95,63 %** |

### Qualité d'extraction (Bourse)

| Indicateur | Valeur |
|---|---|
| Taux d'extraction global (brut) | 68,5 % (52 084 / 76 038 cellules) |
| Champs CIFEN couverts | 138 |
| Lignes (Entreprise × Année) | 551 |
| **Taux de cohérence comptable global** | **96,55 %** (15 573 / 16 129 vérifications, 34 règles actives, 65 entreprises) |

### Comparaison avec la source de référence officielle (OMTPME)

Pour mesurer la fiabilité réelle des données extraites, chaque valeur a été
comparée, champ par champ, à la base officielle de référence :

| Indicateur | Valeur |
|---|---|
| Total comparaisons effectuées | 9 800 |
| **Taux de concordance** | **91,27 %** |
| Écarts détectés | 579 |
| Écarts corrigés | 573 |
| Erreurs d'extraction résiduelles (non corrigées) | 6 |

> Sur les 579 écarts détectés lors de la comparaison, la très grande
> majorité provenait d'erreurs dans la **base officielle elle-même**
> (valeurs manquantes ou obsolètes côté référence), et non de notre
> pipeline d'extraction — confirmé en isolant l'origine de chaque écart
> (source de l'erreur : base officielle vs pipeline interne).



---

## Vue d'ensemble du pipeline

Le projet repose sur **deux pipelines parallèles**, avec la même logique en
trois temps — **Collecte → Extraction/OCR → Vérification comptable** —
appliquée à deux sources de documents très différentes.

```
                 ┌─────────────────────────┐        ┌─────────────────────────┐
                 │   BOURSE DE CASABLANCA   │        │  ENTREPRISES PUBLIQUES  │
                 │   (65 entreprises)       │        │  (19 EEP)               │
                 └───────────┬─────────────┘        └───────────┬─────────────┘
                             │                                    │
                    1. COLLECTE                          1. COLLECTE
              scraping site + AMMC                    fiches de synthèse (source)
              nettoyage pages uniques
              optimisation des rapports
              volumineux
                             │                                    │
                    2. EXTRACTION                         2. EXTRACTION / OCR
              MinerU (extraction de tables)          Tesseract OCR + ancrage de
              Docling OCR (pages complexes)          sections par mots-clés
              mapping vers les champs CIFEN          extraction de 3 tableaux
                             │                        (infos de base, indicateurs
                             │                         éco/fin, immo. corporelles)
                             │                                    │
                    3. VÉRIFICATION                        3. VÉRIFICATION
              règles comptables croisées              règles comptables (identités,
              (Actif=Passif=CPC, sous-totaux)         bornes de plausibilité,
                             │                          stabilité annuelle)
                             └───────────────┬────────────────────┘
                                              │
                                      BASE CIFEN CONSOLIDÉE
```

### 1. Collecte (Bourse de Casablanca)

Dossier `scripts/01_collecte/`.

- Scraping des rapports annuels publiés sur le site de la Bourse de
  Casablanca, avec pagination robuste (gestion des `...` masquant les
  numéros de page), puis en complément sur le site de l'**AMMC**.
- **Nettoyage des pages uniques** (`nettoyage_pages_uniques/`) : détection
  des rapports d'une seule page suspects (souvent de simples communiqués
  renvoyant vers le site plutôt que le vrai rapport), et re-scraping ciblé
  pour retrouver un candidat fiable.
- **Optimisation des rapports volumineux** (`optimisation_volumineux/`) :
  recherche d'une version plus légère (moins de pages) du même rapport en
  ligne, pour accélérer les étapes d'OCR/extraction suivantes, sans jamais
  modifier les originaux (sauvegarde systématique avant tout remplacement).

### 2. Extraction (Bourse de Casablanca)

Dossier `scripts/02_extraction/`.

- **`scraper_identifiants_entreprises.py`** : constitution de la liste de
  référence des entreprises et de leurs identifiants.
- **`mineru_extract_tables.py`** : extraction des tableaux financiers via
  **MinerU** (détection de structure de tableau dans les PDF).
- **`04_docling_ocr_selected_tables.py`** : OCR de secours via **Docling**
  sur les pages où l'extraction MinerU est insuffisante (rapports scannés
  ou mise en page complexe).
- **`01_run_all_reports.py`** : orchestrateur qui enchaîne le traitement
  sur l'ensemble des rapports.
- **`02_audit_selected_tables.py`** : audit des tables extraites avant
  passage au mapping.
- **`03_reprocess_from_existing_mineru.py`** : retraitement ciblé à partir
  de résultats MinerU déjà calculés (évite de tout relancer après un
  ajustement).
- **`05_mapping_cifen_extractor.py`** : mapping final des tableaux extraits
  vers les **champs normalisés du référentiel CIFEN** (Actif, Passif, CPC).

### 3. Vérification (Bourse de Casablanca)

Dossier `scripts/03_verification/`.

- Vérification de l'**équilibre du bilan** (Actif = Passif) et du
  **raccordement du résultat net** (CPC = Passif) — règle de cohérence
  globale.
- Vérification de la **construction de chaque sous-total** (26 règles :
  sous-totaux Actif/Passif, résultats intermédiaires du CPC), pour
  localiser précisément l'origine d'une éventuelle erreur d'extraction.
- Calcul de **taux de remplissage** (extraction) et de **taux de
  cohérence comptable**, en version brute et en version corrigée
  (hors entreprises structurellement hors périmètre CGNC standard :
  banques, sociétés étrangères).

### Entreprises publiques (EEP)

Dossier `extraction_entreprises_publiques/`.

- OCR **100 % local** (Tesseract) des fiches de synthèse EEP, une page par
  entreprise.
- **Ancrage par mots-clés** (`lib/anchors.py`) pour localiser dynamiquement
  chaque section (les libellés varient selon les entreprises : "Informations
  de base" vs "Informations Générales"), plutôt que des coordonnées fixes.
- Extraction de **3 tableaux** par fiche (`lib/extract_table1/2/3.py`) :
  informations générales (sigle, capital, classification juridique...),
  indicateurs économiques et financiers pluriannuels, immobilisations
  corporelles.
- **Fusion** des 3 tableaux en un jeu de données consolidé par entreprise.
- **Validation par règles comptables** (identités CA≥VA, Actif≥Fonds
  propres, stabilité des grandeurs de bilan d'une année sur l'autre,
  plausibilité du coût moyen par employé...) pour détecter les erreurs OCR
  résiduelles sans re-vérification visuelle systématique.

---

## Documentation détaillée des scripts

Chaque sous-dossier de scripts contient un dossier **`readme_scripts/`**
avec la documentation propre à ses scripts (objectif, fonctionnement,
usage, sorties, limites connues). Une documentation consolidée est
également disponible dans `docs/`.

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium      # requis pour les scripts de scraping
```

Dépendance système supplémentaire pour l'OCR (EEP) :
```bash
sudo apt install tesseract-ocr tesseract-ocr-fra   # Linux
```

### Régénérer `requirements.txt`

```bash
pip install pipreqs
pipreqs . --force --encoding utf-8
```

---

## Structure du dépôt

```
fiabilisation_cifen/
├── scripts/
│   ├── 01_collecte/
│   │   ├── nettoyage_pages_uniques/
│   │   ├── optimisation_volumineux/
│   │   └── readme_scripts/
│   ├── 02_extraction/
│   │   └── readme_scripts/
│   └── 03_verification/
│       └── readme_scripts/
├── extraction_entreprises_publiques/
│   └── scripts/
│       ├── lib/
│       ├── pipeline/
│       ├── outils_diagnostic/
│       └── readme_scripts/
├── docs/
└── requirements.txt
```

> Les dossiers de données (`data/`, `Rapports/`, `entreprises_cifen/`,
> `resultats_docling/`, `resultats_mineru/`, `log/`, `.venv/`) sont exclus
> du dépôt via `.gitignore` (voir ce fichier pour le détail).

---

## Contexte académique

| Champ | Détail |
|---|---|
| Établissement | École Nationale des Sciences Appliquées de Safi — Université Cadi Ayyad |
| Département | Département d'Informatique |
| Cycle | Cycle d'ingénieur — Première année |
| Spécialité | Génie Informatique et Intelligence Artificielle |
| Réalisé par | Chaimaa BENRADOUAN |
| Encadrant de stage | Monsieur Abdessamad OURAD |
| Organisme d'accueil | MTPME |
| Période du stage | Du 22 juin 2026 au 28 août 2026 |
| Année universitaire | 2025 – 2026 |