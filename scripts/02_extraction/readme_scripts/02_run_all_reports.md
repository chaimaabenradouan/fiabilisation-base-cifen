# `run_all_reports.py`

## Rôle dans le pipeline

**Lanceur batch** qui applique `mineru_extract_tables.py` à l'ensemble des PDF
collectés, avec une gestion robuste des interruptions, des reprises et des
rapports de fin d'exécution. C'est le point d'entrée principal pour traiter
plusieurs centaines de rapports sans supervision constante.

```
Rapports/<entreprise>/<année>.pdf  (des centaines de PDF)
        │
        ▼
[run_all_reports.py]  ──►  appelle mineru_extract_tables.py pour chaque PDF
        │
        ▼
output/<entreprise>/<année>/  (résultats) + rapports de batch
```

> **Contrainte respectée** : ce script n'importe et ne modifie jamais
> `mineru_extract_tables.py` — il l'appelle en **sous-processus** (`subprocess`),
> ce qui garantit une isolation totale (un crash sur un PDF n'affecte pas les
> autres) et permet de le faire évoluer indépendamment.

## Fonctionnalités principales

### 1. Reprise automatique après interruption
Un registre persistant `completed.json` mémorise chaque PDF déjà traité avec
succès. Au redémarrage, seuls les PDF manquants ou en échec sont retraités.
La détection de complétion est **doublement vérifiée** : présence dans le
registre **ET** existence réelle des fichiers de sortie (`selected_tables/*.png`)
sur disque — jamais basée sur une date de modification, jugée non fiable.

### 2. Écriture atomique du registre
Le fichier `completed.json` est écrit via un fichier temporaire puis renommé
(`tmp.replace(path)`), pour éviter toute corruption du registre en cas de
crash pendant l'écriture (coupure électrique, Ctrl+C mal placé...).

### 3. Filtrage des PDF trop volumineux
Deux seuils indépendants, cumulables :
- `--max-pages` (défaut : **20 pages**) — au-delà, le PDF est jugé trop lourd
  pour un traitement OCR/MinerU raisonnable sans GPU dédié.
- `--max-pdf-size-mb` — seuil optionnel en mégaoctets.

Les PDF filtrés ne sont **ni SUCCESS ni FAILED** : ils sont listés séparément
dans `large_pdfs.json` pour un traitement dédié ultérieur (ex. sur une machine
plus puissante), sans polluer les statistiques d'échec.

### 4. États explicites par PDF
| État | Signification |
|---|---|
| `SUCCESS` | Traité avec succès, fichiers de sortie complets |
| `SKIPPED` | Déjà traité lors d'un run précédent |
| `SKIPPED_LARGE` | Ignoré car trop volumineux (pages ou taille) |
| `FAILED` | Échec (erreur MinerU, sortie incomplète...) |

### 5. Option `--retry-failed`
Relance uniquement les PDF listés en échec lors du run précédent
(`failed_pdfs.json`), sans retraiter tout le lot.

### 6. Rapport final détaillé
En fin de batch, trois fichiers sont générés dans le dossier de sortie :
- `batch_report.json` — statistiques complètes (durée, temps moyen/PDF, etc.)
- `failed_pdfs.json` — liste des échecs avec message d'erreur
- `large_pdfs.json` — liste des PDF volumineux mis de côté

Une barre de progression (`tqdm`) affiche en temps réel l'avancement global,
le temps moyen par PDF et une estimation du temps restant (ETA).

## Utilisation (CLI)

```bash
python run_all_reports.py --rapports-dir Rapports --output-dir output
python run_all_reports.py --output-dir output --max-pages 30
python run_all_reports.py --output-dir output --retry-failed
```

| Argument | Rôle | Défaut |
|---|---|---|
| `--rapports-dir` | Dossier racine des PDF (`<entreprise>/<année>.pdf`) | `Rapports` |
| `--output-dir` | Dossier racine des sorties | `output` |
| `--backend` | Backend MinerU | `pipeline` |
| `--serie-preference` | `social` ou `consolide` | `social` |
| `--retry-failed` | Ne relance que les échecs précédents | — |
| `--max-pdf-size-mb` | Seuil de taille en Mo | aucun |
| `--max-pages` | Seuil de pages (0 = désactivé) | `20` |

## Structure attendue des données d'entrée

```
Rapports/
├── SOCIETE_A/
│   ├── 2021.pdf
│   ├── 2022.pdf
│   └── 2023.pdf
└── SOCIETE_B/
    └── 2022.pdf
```

## Pourquoi ce script est robuste (pensé pour un usage réel, longue durée)

- **Tolérance aux pannes** : un batch de plusieurs centaines de PDF peut
  durer des heures ; toute interruption (coupure, fermeture du terminal) ne
  fait perdre aucun travail déjà accompli.
- **Isolation par sous-processus** : un PDF corrompu ou un crash MinerU sur un
  document ne bloque jamais le reste du batch.
- **Séparation claire des causes d'échec** (volumineux vs erreur réelle),
  essentielle pour prioriser le travail correctif.
