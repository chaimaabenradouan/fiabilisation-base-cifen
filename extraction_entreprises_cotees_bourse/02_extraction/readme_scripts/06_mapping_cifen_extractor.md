# `cifen_extractor.py`

## Rôle dans le pipeline

Étape de **mapping** : ce script prend les CSV bruts issus de l'OCR Docling
(`bilan_actif.csv`, `bilan_passif.csv`, `cpc.csv`) et associe chaque ligne à
un **code CIFEN officiel**, pour produire des données structurées et
comparables entre entreprises et entre années.

```
docling_result/tables_csv/{bilan_actif,bilan_passif,cpc}.csv
        │
        ▼
[cifen_extractor.py]  ──►  data_cifen.csv (tableau large, un code CIFEN par colonne)
                            data_complet.csv (format long, toutes années)
                            data_verification.csv (dérivé vs rapport réel)
                            _non_mappes.csv (lignes non reconnues)
                            _matches_incertains.csv (correspondances à faible confiance)
        │
        ▼
data_totale.csv  (cumul global, toutes entreprises confondues)
```

## Entrées / Sorties

**Entrée :** pour une entreprise et une liste d'années, les 3 CSV Docling
(`bilan_actif.csv`, `bilan_passif.csv`, `cpc.csv`) situés sous
`output/{entreprise}/{annee}/docling_result/` (avec repli automatique en
recherche récursive si le sous-dossier `tables_csv/` n'existe pas).

**Sorties**, à la racine de l'entreprise (`output/{entreprise}/`) :

| Fichier | Contenu |
|---|---|
| `data_complet.csv` | Format long : `Bilan;Champ_Original;Annee;Valeur`, toutes années traitées y compris les "bonus" |
| `data_cifen.csv` | Format large : une ligne par (Entreprise, Année), une colonne par code CIFEN |
| `data_verification.csv` | Comparaison valeur dérivée (via colonne N-1) vs valeur du vrai rapport, quand ce dernier existe aussi sur le disque |
| `_non_mappes.csv` | Libellés qu'aucun code CIFEN n'a pu absorber avec confiance suffisante |
| `_matches_incertains.csv` | Lignes mappées mais avec un score de confiance faible, à auditer |
| `_erreurs.log` | Erreurs de lecture rencontrées |

**Sortie globale**, à la racine du projet : `data_totale.csv` — cumulatif sur
toutes les entreprises traitées. Relancer une entreprise déjà présente
**ne remplace que ses lignes** (clé `Entreprise + Annee`), les autres
entreprises sont conservées intactes.

## Logique métier

### 1. Dictionnaire CIFEN avec alias
Chaque code CIFEN (ex. `Actif_C3`) peut être associé à **plusieurs libellés
possibles** dans les dictionnaires `ACTIF_FIELDS`, `PASSIF_FIELDS`,
`CPC_FIELDS` — car un même poste comptable s'écrit différemment selon les
rapports ("Total Actif" vs "Total général I+II+III", "Banques T.G. et
C.C.P." vs "Banques Trésorerie Générale et Chèques postaux"...). Les entrées
marquées `[EXT]` sont des ajouts (lignes de totaux, alias fréquents) qui ne
figuraient pas dans la liste CIFEN d'origine mais existent systématiquement
dans les bilans réels et servent à la vérification.

### 2. Normalisation des libellés OCR (`normalize_label`)
Avant toute comparaison, chaque libellé brut est nettoyé :
- suppression des accents et de la ponctuation,
- suppression de la numérotation de tête ("I.", "12.", "VII :"),
- traitement des parenthèses : le contenu **court** (référence type "(A)",
  "(2)") est supprimé, mais le contenu **plus long** (souvent une formule
  utile comme "(A+B+C+D+E)") est conservé — car il aide à distinguer deux
  champs proches (ex. "Total I" vs "Total II F+G+H+I"),
- recollage des sigles éclatés par la ponctuation (ex. "T G C P" → "tgccp"),
  pour qu'ils redeviennent comparables à leur équivalent en toutes lettres.

### 3. Matching en 2 passes (le cœur du script)

**Le problème de l'ancienne approche** : un simple pointeur avançant ligne
par ligne dans une fenêtre étroite créait un **effet domino** — dès qu'une
ligne était mal reconnue (fusion OCR, libellé légèrement différent, ligne
vide imprévue), le pointeur restait décalé et toutes les lignes suivantes de
la section pouvaient se retrouver alignées sur le mauvais champ.

**Nouvelle approche (`align_rows_to_fields`) :**

- **Passe 1 — haute confiance, indépendante de la position** : chaque ligne
  brute est comparée à **toute** la liste canonique (pas seulement une
  fenêtre proche). Les correspondances quasi certaines (score ≥ 0.90) sont
  validées immédiatement, où qu'elles soient dans la liste — via une
  assignation gloutonne globale (tri de toutes les paires ligne/champ par
  score décroissant). Cela plante des "ancres" fiables un peu partout dans la
  section, ce qui empêche un décalage local de se propager à toute la suite.

- **Passe 2 — positionnelle avec marge de sécurité** : pour ce qui reste, la
  recherche se fait autour de la position attendue (fenêtre de 6 lignes,
  élargie à 14 si rien de valable), mais le match n'est accepté **que** s'il
  dépasse le seuil (0.5) **et** qu'il a une marge suffisante (≥ 0.06) par
  rapport au deuxième meilleur candidat. Sinon, la ligne reste **non
  mappée** plutôt que de deviner un mauvais champ — principe directeur du
  script : *mieux vaut un trou visible dans `_non_mappes.csv` qu'une fausse
  valeur silencieuse.*

### 4. Parsing des nombres (`parse_number`)
Gère les formats numériques marocains réels rencontrés dans les rapports :
espace ou point comme séparateur de milliers, virgule décimale, parenthèses
pour les valeurs négatives, et lève l'ambiguïté entre notation FR et US selon
le nombre de décimales détecté après le dernier séparateur.

### 5. Détection du format de colonnes (`detect_value_col_count`)
Les CSV Docling n'ont pas toujours le même nombre de colonnes de valeurs
selon la mise en page du rapport source :
- **mode `full`** (4-5 colonnes) : Brut, Amortissement, Net, Net N-1
- **mode `simple`** (2-3 colonnes) : Net, Net N-1 (format "banque" plus
  condensé)

Le script détecte automatiquement le mode par la longueur de ligne la plus
fréquente, et adapte l'extraction en conséquence.

> **Note sur la colonne "Verification"** : quand elle est présente (5e
> colonne), elle n'est **jamais lue ni interprétée** — son contenu a été
> corrigé/validé manuellement en amont par un humain (étape Docling) et n'a
> plus de signification à analyser automatiquement. Une ligne est traitée
> de façon identique que cette colonne soit présente, absente, vide ou remplie.

### 6. Détection des lignes-titres parasites
Certains CSV contiennent une deuxième ligne d'en-tête parasite (ex. "PASSIF
/ KDH") qui a échappé à la détection normale. Le script la repère par un
critère strict à trois conditions cumulées (mot de section **et** unité
monétaire **et** absence de toute valeur numérique sur la ligne), pour ne
jamais confondre avec un vrai champ comptable comme "Capitaux propres".

### 7. Planification des années (`planifier_annees`)
Un bilan marocain affiche systématiquement 2 colonnes de valeurs : l'année en
cours et l'année précédente (N-1). Le script exploite cette redondance :

- **Chaque année explicitement demandée est toujours son "ancre"** : son
  propre rapport est ouvert sur le disque, même si elle est consécutive à une
  autre année demandée.
- **Chaque ancre tente de récupérer gratuitement l'année N-1** via sa colonne
  "Net N-1", **si** cette année n'est pas déjà couverte par ailleurs. Les
  ancres sont traitées de la plus récente à la plus ancienne, pour que ce
  soit toujours l'ancre la plus proche qui "gagne" un écart entre deux années
  demandées non consécutives.
- **Limite inhérente assumée** : un bilan n'a que 2 colonnes de valeurs, donc
  on ne peut jamais récupérer plus d'une année en arrière par ancre. Si
  l'écart entre deux années demandées est de 2 ans ou plus, l'année
  intermédiaire la plus éloignée reste manquante sauf si elle est elle-même
  demandée explicitement.

### 8. Vérification croisée des années dérivées
Pour chaque année récupérée "gratuitement" (via N-1), le script vérifie si un
**vrai rapport** existe aussi sur le disque pour cette année précise. Si oui,
il l'ouvre **uniquement pour comparer** (jamais pour remplacer la valeur
dérivée) et alimente `data_verification.csv` avec l'écart constaté — un
contrôle qualité gratuit qui ne coûte qu'une lecture de fichier
supplémentaire.

### 9. Fusion idempotente des sorties (`merge_and_write`)
Chaque écriture de CSV **fusionne** avec le fichier existant plutôt que de
l'écraser : seules les lignes dont la clé (`Entreprise + Annee`, ou
`Bilan + Annee`) correspond à un nouveau traitement sont remplacées ; les
autres lignes déjà présentes (autres entreprises, autres années) sont
conservées telles quelles. Une **migration de schéma automatique** est gérée
si le fichier existant a été écrit avec un ancien format de colonnes : le
fichier est alors régénéré proprement plutôt que de faire planter le script,
avec un avertissement explicite à l'utilisateur.

## Utilisation (CLI)

```bash
# Une seule entreprise
python cifen_extractor.py afma_SA 2016 2017 2025

# Plusieurs entreprises via un fichier journal (CSV "entreprise;annees")
python cifen_extractor.py --journal mon_journal.csv

# Personnaliser la racine des données et le fichier cumulatif global
python cifen_extractor.py afma_SA 2016 2017 2025 --root output --totale-path data_totale.csv
```

| Argument | Rôle | Défaut |
|---|---|---|
| `entreprise` | Nom exact du dossier entreprise | — |
| `annees` | Liste des années à traiter | — |
| `--journal` | Fichier CSV pour traiter plusieurs entreprises en un run | — |
| `--root` | Dossier racine des données | `output` |
| `--tables-subdir` | Sous-dossier des CSV Docling | `tables_csv` |
| `--totale-path` | Chemin du fichier cumulatif global | `data_totale.csv` |

## Pourquoi ce script illustre une démarche rigoureuse

- **Aucune valeur inventée** : à chaque étape ambiguë (matching incertain,
  fusion de ligne, écart de vérification), le script préfère signaler le
  doute (`_non_mappes.csv`, `_matches_incertains.csv`,
  `data_verification.csv`) plutôt que de deviner silencieusement.
- **Vérification croisée gratuite** intégrée nativement dans la logique de
  planification des années, sans coût de traitement supplémentaire notable.
- **Idempotence** : relancer le script plusieurs fois (même partiellement,
  entreprise par entreprise) ne corrompt jamais les données déjà produites
  pour les autres entreprises ou années.
- **Traçabilité complète** : chaque valeur du tableau large peut être
  retracée jusqu'au libellé original OCR et à son score de confiance de
  matching.
