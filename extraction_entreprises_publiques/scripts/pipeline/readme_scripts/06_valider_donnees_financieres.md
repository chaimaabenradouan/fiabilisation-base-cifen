# Documentation du script `06_valider_donnees_financieres.py`

**Objectif** : Vérifier la cohérence financière et comptable des données extraites (principalement du Tableau 2), afin de détecter les erreurs d’OCR résiduelles **sans avoir besoin de regarder les images**.

---

## 1. Présentation générale

Ce script est la **dernière étape** de la chaîne de traitement.  
Il ne modifie pas les données : il les **contrôle** en appliquant un ensemble de règles comptables et de cohérence.

Principe fondamental :
> Plusieurs grandeurs du tableau sont liées par des **identités comptables** qui doivent être vraies.  
> Une violation signale presque toujours une **valeur mal lue** (erreur d’OCR), et non une vraie anomalie financière de l’entreprise.

---

## 2. Usage

```bash
python3 06_valider_donnees_financieres.py chemin/vers/table2.csv
python3 06_valider_donnees_financieres.py chemin/vers/table2.csv --out rapport.csv
```

| Argument     | Description                                      | Obligatoire |
|--------------|--------------------------------------------------|-------------|
| `csv_path`   | CSV des indicateurs économiques et financiers    | Oui         |
| `--out`      | Chemin du rapport CSV détaillé                   | Non         |

Si `--out` n’est pas fourni et que des anomalies sont détectées, un fichier `*_anomalies.csv` est créé automatiquement à côté du CSV source.

---

## 3. Les 8 règles de validation

### R1 – Identité du solde technique
**Formule** :  
`Solde technique = Cotisations et contributions – Pensions et prestations`

- Applicable surtout aux caisses de retraite / sécurité sociale (CMR, CNSS RG, CNSS AMO).
- Tolérance : ±2 (arrondis d’affichage).
- Détecte particulièrement les **signes manquants** (magnitude correcte mais signe inversé).
- Si l’écart porte sur la magnitude (et pas seulement le signe) → sévérité abaissée en **ALERTE** (peut être légitime si une 3ᵉ composante existe, ex. Unité Médicale à la CNSS).

### R2 – Total actif ≥ Fonds propres
L’actif finance les capitaux propres + les dettes.  
Donc : `Total actif ≥ Fonds propres` (toujours vrai).

### R3 – Total actif ≥ Dettes de financement
Même logique : l’actif doit être au moins aussi grand que les dettes de financement.

### R4 – Chiffre d’affaires ≥ Valeur ajoutée
La valeur ajoutée est un sous-agrégat du chiffre d’affaires.  
Elle ne peut **jamais** le dépasser.

### R5 – Coût moyen par employé
```
Charges de personnel / Effectif  ∈  [30 000 ; 900 000] MAD/an
```
Détecte les effectifs ou charges de personnel mal lus (chiffre tronqué, zéro en trop, etc.).

### R6 – Stabilité année-sur-année des grandeurs de « stock »
Indicateurs concernés :
- `effectif`
- `effectif_du_groupe`
- `total_actif`
- `dettes_financement`

Un ratio > 3× ou < 1/3× d’une année sur l’autre est **suspect**.

**Note** : `fonds_propres` est volontairement exclu (une recapitalisation peut légitimement le faire bondir).

### R7 – Signes attendus
- `effectif` et `effectif_du_groupe` > 0
- `total_actif` > 0

### R8 – Complétude
Signale les entreprises avec **trop peu de champs remplis** (indice fort que l’extraction a largement échoué sur cette page).

---

## 4. Niveaux de sévérité

| Sévérité   | Signification                                      |
|------------|----------------------------------------------------|
| **ERREUR** | Violation d’une identité comptable ou valeur impossible |
| **ALERTE** | Situation suspecte mais qui peut parfois être légitime |

---

## 5. Fonctionnement technique

1. Lecture du CSV
2. Regroupement des colonnes par indicateur et par année (`parse_row_fields`)
3. Application successive des 8 règles
4. Affichage d’un rapport lisible dans le terminal
5. Génération d’un CSV détaillé (une ligne par anomalie)

### Structure du rapport CSV

| Colonne     | Contenu                          |
|-------------|----------------------------------|
| `dossier`   | Nom de l’entreprise              |
| `regle`     | R1 à R8                          |
| `severite`  | ERREUR ou ALERTE                 |
| `champ`     | Champ concerné                   |
| `message`   | Explication détaillée            |

---

## 6. Place dans la chaîne de traitement

```
01_extraire_table1.py
02_extraire_table2.py
03_extraire_table3.py
04_fusionner_table1_table2.py
05_fusionner_table3_final.py
06_valider_donnees_financieres.py   ← ce script
```

C’est l’étape de **contrôle qualité** finale avant exploitation des données.

---

## 7. Points importants

- Le script ne corrige **jamais** les valeurs : il se contente de signaler.
- Les règles ont été calibrées empiriquement sur les entreprises du corpus (notamment CMR, CNSS, RAM, HAO…).
- Les grandeurs de « flux » (résultat net, CAF…) ne sont volontairement pas soumises à des contrôles de stabilité année-sur-année, car elles peuvent légitimement varier fortement.

---

## 8. Conclusion

Le script `06_valider_donnees_financieres.py` permet de détecter automatiquement la majorité des erreurs d’OCR restantes grâce à des identités comptables simples et robustes.  
Il constitue un filet de sécurité essentiel avant toute utilisation des données extraites.
