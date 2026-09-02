# Documentation du script `auto_extract_ddg.py`

**Objectif** : À partir d’une liste de noms d’entreprises, retrouver automatiquement leur fiche sur **welipro.com** et extraire les informations légales principales (ICE, RC, IF, Capital, Forme juridique, Date de création), **sans aucune clé API**.

---

## 1. Présentation générale

Ce script automatise la recherche d’informations légales d’entreprises marocaines en combinant :

1. **DuckDuckGo** (via la librairie `ddgs` / `duckduckgo-search`) pour trouver la fiche welipro.com
2. **Vérification stricte du nom** pour éviter les faux positifs
3. **Extraction ciblée** des champs depuis le HTML de la fiche

Il est conçu pour être fiable plutôt que exhaustif : mieux vaut un « NON TROUVÉ » qu’une mauvaise donnée.

---

## 2. Installation

```bash
pip install ddgs requests beautifulsoup4
```

> Note : le package s’appelait auparavant `duckduckgo-search`. Le script gère les deux noms.

---

## 3. Usage

```bash
python auto_extract_ddg.py entreprises.csv resultats.csv
```

### Format du CSV d’entrée

Le fichier doit contenir **au minimum** une colonne :

```csv
Nom_Entreprise
AFMA SA
CFG BANK
TAQA MOROCCO
...
```

### Format du CSV de sortie

| Colonne            | Description                                      |
|--------------------|--------------------------------------------------|
| `Nom_Entreprise`   | Nom fourni en entrée                             |
| `ICE`              | Identifiant Commun de l’Entreprise               |
| `RC`               | Registre de Commerce (numéro + ville)            |
| `IF`               | Identifiant Fiscal                               |
| `Capital`          | Capital social                                   |
| `Forme_juridique`  | Forme juridique                                  |
| `Date_creation`    | Date de création                                 |
| `Source`           | Source des données                               |
| `URL_Source`       | Lien vers la fiche welipro                       |
| `Statut`           | `TROUVÉ` ou `NON TROUVÉ`                         |

---

## 4. Fonctionnement détaillé

### 4.1 Recherche DuckDuckGo

Le script teste plusieurs requêtes :

```python
queries = [
    f'site:maroc.welipro.com {nom_entreprise}',
    f'"{nom_entreprise}" welipro ICE RC IF Maroc',
    f'{nom_entreprise} maroc.welipro.com ICE',
]
```

Il ne garde que les résultats qui pointent vers une fiche welipro (`/c/` dans l’URL).

### 4.2 Vérification stricte du nom (`names_match`)

C’est le point le plus important du script.

Avant d’accepter une fiche, le script :
- Normalise les deux noms (minuscules, sans accents, sans ponctuation)
- Vérifie que **au moins 90 % des mots significatifs** de la requête se retrouvent dans le nom de la page

**Exemple** :
- Requête : `Wafa Assurance`
- Page trouvée : `AGL Assurances` → **rejeté** (couverture trop faible)
- Page trouvée : `AFMA SA` pour la requête `AFMA` → **accepté**

Cette règle évite les confusions dangereuses (ex. BANQUE CENTRALE POPULAIRE vs Banque Populaire Patrimoine II).

### 4.3 Extraction des champs

Pour chaque champ, le script isole d’abord le **bloc de texte** situé entre le label et le label suivant, puis applique une regex ciblée :

| Champ              | Méthode d’extraction                          |
|--------------------|-----------------------------------------------|
| ICE                | Suite de 9 à 20 chiffres                      |
| RC                 | Numéro + ville entre parenthèses si présente  |
| IF                 | Suite de 3 à 15 chiffres                      |
| Capital            | Chiffres + devise (MAD, DHS…)                 |
| Forme juridique    | Texte libre (première ligne)                  |
| Date de création   | Format JJ/MM/AAAA                             |

### 4.4 Reprise automatique

Si le fichier de sortie existe déjà partiellement, le script **ne retrait pas** les entreprises déjà présentes.  
Il reprend là où il s’était arrêté.

---

## 5. Paramètres importants

| Paramètre                  | Valeur par défaut | Rôle                                          |
|---------------------------|-------------------|-----------------------------------------------|
| `SIMILARITY_THRESHOLD`    | 0.90              | Seuil de similarité des noms (très strict)    |
| `SEARCH_MIN_DELAY`        | 3.0 s             | Délai minimum entre recherches DuckDuckGo     |
| `SEARCH_MAX_DELAY`        | 6.0 s             | Délai maximum entre recherches                |
| `FETCH_MIN_DELAY`         | 2.0 s             | Délai minimum entre téléchargements de pages  |
| `FETCH_MAX_DELAY`         | 4.0 s             | Délai maximum entre téléchargements           |
| `DEBUG`                   | `True`            | Affiche les détails de matching (à désactiver en prod) |

---

## 6. Points de robustesse

| Situation                              | Comportement                                      |
|----------------------------------------|---------------------------------------------------|
| Aucune fiche trouvée                   | Statut = `NON TROUVÉ`                             |
| Fiche trouvée mais nom différent       | Rejetée (évite les faux positifs)                 |
| Erreur réseau / timeout                | Nouvelle tentative (jusqu’à 3 fois)               |
| Fichier de sortie déjà partiellement rempli | Reprise automatique                          |
| Package `ddgs` ou `duckduckgo_search`  | Les deux sont gérés                               |

---

## 7. Limites

- Dépend de la disponibilité de DuckDuckGo et de welipro.com
- Les délais sont volontiers prudents pour éviter les blocages
- Certaines entreprises absentes de welipro resteront en `NON TROUVÉ`
- Le matching est volontairement strict → quelques vrais positifs peuvent être manqués

---

## 8. Conseils d’utilisation

1. Commence avec `DEBUG = True` pour comprendre les rejets
2. Une fois satisfait, passe `DEBUG = False`
3. Ne descends pas trop les délais (risque de blocage)
4. Vérifie manuellement quelques lignes du CSV de sortie

---

## 9. Conclusion

`auto_extract_ddg.py` permet d’enrichir automatiquement une liste d’entreprises avec leurs identifiants légaux (ICE, RC, IF…) en s’appuyant uniquement sur des sources publiques et sans clé API.  
Sa force principale réside dans la **vérification stricte des noms**, qui privilégie la fiabilité des données à la quantité.
