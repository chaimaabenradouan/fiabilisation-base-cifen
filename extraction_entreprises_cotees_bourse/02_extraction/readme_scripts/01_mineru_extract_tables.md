# `mineru_extract_tables.py`

## Rôle dans le pipeline

Script **cœur** de l'étape d'extraction (`02_extraction/`). Il ne fait pas de
localisation de tableaux lui-même : il s'appuie sur les tableaux **déjà
détectés par MinerU** (via son fichier `content_list.json`) et se concentre
sur une tâche précise :

> Parmi tous les tableaux détectés dans un rapport financier (PDF), identifier
> lesquels correspondent à **Identification**, **Bilan Actif**, **Bilan
> Passif** et **CPC**, et ne conserver **qu'une seule série cohérente**
> (comptes sociaux **OU** comptes consolidés) quand le rapport contient les
> deux.

```
PDF ──► [mineru_extract_tables.py] ──► 4 images PNG des tableaux pertinents
                                        + 1 JSON de traçabilité complet
```

Ce script n'est presque jamais lancé seul en pratique : il est soit appelé en
sous-processus par `01_run_all_reports.py` (traitement en masse), soit importé
comme module par `03_reprocess_from_existing_mineru.py` (retraitement sans
relancer MinerU). C'est pour cette raison qu'il **ne porte pas de préfixe
numérique** dans l'arborescence : c'est un module, pas un point d'entrée.

## Entrées / Sorties

**Entrée :** un PDF de rapport financier (comptes sociaux d'une société cotée
à la Bourse de Casablanca).

**Sorties**, dans `<output_dir>/` :
- `selected_tables/identification.png`
- `selected_tables/bilan_actif.png`
- `selected_tables/bilan_passif.png`
- `selected_tables/cpc.png`
- `<pdf_stem>_tables_analysis.json` — JSON détaillé listant **tous** les
  tableaux détectés, leur score par catégorie, la série comptable identifiée,
  et le raisonnement complet ayant mené à la sélection (traçabilité totale).

## Logique métier

### 1. Dictionnaires de mots-clés pondérés (nomenclature CGNC)
Le script reprend la nomenclature du **Plan Comptable Général Marocain
(CGNC)** : chaque rubrique comptable (ex. "trésorerie actif", "total du
passif", "chiffre d'affaires") est associée à un poids. Un poste structurant
et caractéristique pèse lourd (ex. `tresorerie actif`: 22), un terme ambigu
partagé entre catégories pèse peu (ex. `personnel`: 3), afin qu'aucun mot
générique ne décide seul de la classification.

### 2. Détection de la série comptable (social vs consolidé)
Le script recherche des mentions explicites ("comptes sociaux", "comptes
consolidés", "états financiers sociaux"...) dans le flux de blocs qui
précèdent chaque tableau. En complément, une **seconde couche de détection**
s'appuie sur le contenu même du tableau : certaines rubriques (intérêts
minoritaires, écart d'acquisition, goodwill, périmètre de consolidation...)
n'existent structurellement que dans des comptes consolidés — leur présence
suffit à trancher même sans mention textuelle explicite à proximité.

### 3. Scoring et classification
Chaque tableau reçoit un score par catégorie (identification, bilan actif,
bilan passif, cpc). Le tableau n'est classé que si :
- son meilleur score dépasse un seuil minimal (`MIN_SCORE_THRESHOLD = 32`),
- et l'écart avec le deuxième meilleur score est suffisant
  (`MIN_SCORE_MARGIN = 6`), pour éviter de trancher sur un signal ambigu.

Une vérification spécifique évite de confondre le CPC avec l'**État des
Soldes de Gestion (ESG)**, une annexe CGNC qui partage du vocabulaire avec le
CPC sans en être un.

### 4. Réparation des bilans coupés en deux blocs
Un bilan CGNC complet a toujours 3 sections obligatoires (ex. pour l'actif :
immobilisé / circulant / trésorerie). Quand MinerU détecte la page en
plusieurs blocs séparés, chaque moitié peut individuellement dépasser le
seuil de score et être sélectionnée à tort à la place du bilan complet. Le
script détecte les tableaux **partiels** et va chercher, parmi les tableaux
voisins (même série comptable, proximité dans l'ordre de lecture), ceux qui
portent les sections manquantes, pour les **fusionner automatiquement**
(texte + image empilée verticalement).

### 5. Sélection d'une série unique et cohérente
Pour l'ensemble du document, le script choisit la série (sociale ou
consolidée) offrant la meilleure couverture (nombre de catégories trouvées),
puis le meilleur score cumulé, puis en dernier recours la préférence
utilisateur (`--serie-preference`, défaut : `social`).

## Utilisation (CLI)

```bash
python mineru_extract_tables.py --pdf rapport.pdf
python mineru_extract_tables.py --pdf rapport.pdf --serie-preference consolide
python mineru_extract_tables.py --pdf rapport.pdf --skip-mineru --mineru-output out/
```

| Argument | Rôle |
|---|---|
| `--pdf` | Chemin du PDF à traiter (obligatoire) |
| `--output-dir` | Dossier de sortie (défaut : `./output/<nom_pdf>/`) |
| `--mineru-output` | Dossier de sortie MinerU à utiliser/produire |
| `--lang` | Langue OCR à forcer (uniquement écritures non latines) |
| `--backend` | Backend MinerU (`pipeline` par défaut) |
| `--skip-mineru` | Réutilise une sortie MinerU déjà produite (gain de temps) |
| `--serie-preference` | `social` ou `consolide` en cas d'égalité |
| `--verbose` | Active les logs DEBUG |

## Pourquoi ce script est robuste

- **Aucune dépendance à des coordonnées géométriques (bbox)** : toute la
  logique s'appuie sur l'ordre de lecture déjà garanti par MinerU, ce qui
  rend le script tolérant aux mises en page variées des rapports marocains.
- **Traçabilité totale** : chaque décision (score, mots-clés reconnus, série
  choisie, fusion de tableaux) est justifiée dans le champ `reasoning` du
  JSON de sortie — indispensable pour l'audit qualité en aval.
- **Robustesse à l'absence de Pillow** : le script reste fonctionnel (simple
  copie de fichier) même sans cette dépendance, pour ne pas bloquer un
  pipeline industriel sur un composant non critique.
