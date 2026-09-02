# `audit_selected_tables.py`

## Rôle dans le pipeline

Script de **contrôle qualité léger**. Il ne relance **rien** (pas MinerU, pas
d'OCR) : il relit uniquement les fichiers `*_tables_analysis.json` déjà
produits par `mineru_extract_tables.py` / `run_all_reports.py`, et identifie
les sélections **suspectes** à vérifier manuellement.

```
output/**/*_tables_analysis.json  (déjà produits)
        │
        ▼
[audit_selected_tables.py]  ──►  audit_report.csv  (uniquement les cas à risque)
```

C'est l'étape qui permet de passer d'un traitement automatique massif à une
**vérification humaine ciblée**, sans avoir à relire des centaines de
documents un par un : seuls les cas flagués nécessitent une relecture.

## Logique de détection des anomalies (flags)

| Flag | Signification |
|---|---|
| `LOW_CONFIDENCE` | Score de confiance du tableau sélectionné < 0.5 |
| `FEW_KEYWORDS` | Moins de 2 mots-clés comptables reconnus dans le tableau |
| `NOT_TABULAR` | La structure HTML détectée ne ressemble pas à un vrai tableau |
| `NARROW_SUBTABLE` | Aucune des grandes sections structurantes du bilan (immobilisé/circulant/trésorerie pour l'actif, etc.) n'est présente — signe probable d'un **sous-tableau de détail** sélectionné à la place du bilan complet |
| `PARTIAL_UNRESOLVED` | Le tableau reste partiel malgré la tentative de fusion automatique (aucun voisin complémentaire trouvé) |
| `SERIE_CONFLICT` | Le contexte textuel indiquait une série (ex. "social") mais le contenu du tableau contredit ce choix (ex. présence de "intérêts minoritaires") |
| `AMBIGUOUS_SCORE` | L'écart de score avec la catégorie concurrente la plus proche est trop faible (≤ 8 points) |
| `CROSS_SIGNAL` | La catégorie concurrente a en réalité un score **supérieur** au tableau retenu — signal fort d'erreur de classification |
| `MULTI_SERIE_AMBIGUOUS` | Le document contient à la fois des comptes sociaux ET consolidés, rendant le choix de série potentiellement ambigu |

### Historique d'un correctif clé : `NARROW_SUBTABLE`

Le flag original se basait sur la simple présence des mots "total actif" /
"total passif" dans les mots-clés reconnus. Un cas réel (**CASH_PLUS S.A.,
2025**) a montré que ce critère générait à la fois des faux positifs et
ratait un vrai bug : un sous-tableau isolé ("Immobilisations" seul) avait été
sélectionné à la place du bilan complet, sans lien avec la question
sociale/consolidée. Le critère a été remplacé par `NARROW_SUBTABLE`, qui
vérifie la présence d'**au moins une des 3 grandes sections structurantes**
d'un bilan complet (immobilisé, circulant, trésorerie) — un sous-tableau de
détail n'en couvre typiquement aucune, même s'il obtient un score élevé sur
des mots-clés de détail.

## Sortie

Un fichier `audit_report.csv` contenant une ligne par **catégorie suspecte**
(pas par document entier — un même document peut apparaître plusieurs fois
si plusieurs de ses tableaux sont flagués), avec les colonnes :

`fichier`, `document`, `categorie`, `table_id`, `confidence`, `serie_choisie`,
`series_detectees`, `flags`

La console affiche également une répartition globale des flags (comptage par
type), pour avoir une vue d'ensemble immédiate de la qualité du batch.

## Utilisation (CLI)

```bash
python audit_selected_tables.py --output-dir /chemin/vers/output
python audit_selected_tables.py --output-dir /chemin/vers/output --csv-out mon_audit.csv
```

| Argument | Rôle | Défaut |
|---|---|---|
| `--output-dir` | Dossier racine où chercher récursivement les `*_tables_analysis.json` | obligatoire |
| `--csv-out` | Chemin du CSV de sortie | `audit_report.csv` |

## Pourquoi cette étape est indispensable dans un pipeline "propre et pro"

- Elle rend le contrôle qualité **scalable** : sur plusieurs centaines de
  documents, une relecture manuelle intégrale serait impossible ; l'audit
  cible uniquement les 5–10 % de cas réellement douteux.
- Elle est **non destructive** : aucun fichier de sortie n'est modifié, ce
  qui permet de la relancer à volonté sans risque.
- Elle documente précisément **pourquoi** chaque cas est suspect (et pas
  seulement qu'il l'est), ce qui accélère considérablement la relecture
  humaine.
