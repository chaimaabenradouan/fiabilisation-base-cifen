# Documentation — `02_detecter_rapports_volumineux.py` (anciennement detect_volumineux_from_json.py)

## 1. Rôle dans le pipeline

Ce script prend en entrée le fichier `rapport_pages.json` (produit par `count_pdf_pages.py`) et identifie, parmi tous les rapports, ceux considérés comme **"volumineux"** (dépassant un certain seuil de pages). Ces rapports volumineux sont ceux qui bénéficieront ensuite d'une tentative d'optimisation par `smart_scrape_batch.py` (recherche d'une version plus légère en ligne).

## 2. Critère de détection

Un rapport est considéré "volumineux" si son nombre de pages est **supérieur ou égal** à `SEUIL_VOLUMINEUX`, fixé à **20 pages par défaut** dans le code (constante modifiable directement en tête de fichier, pas de paramètre en ligne de commande pour ce seuil).

## 3. Fonctionnement étape par étape

1. **Chargement** de `rapport_pages.json` (`load_json_data`). Si le fichier est introuvable, le script affiche une erreur explicite invitant à exécuter d'abord `count_pdf_pages.py`, puis s'arrête (`exit(1)`).
2. **Parcours de toutes les entreprises et années** (`detect_voluminous_from_json`) :
   - Pour chaque rapport, comparaison du nombre de pages au seuil.
   - Si `pages >= SEUIL_VOLUMINEUX`, le rapport est ajouté à la liste des volumineux pour cette entreprise, avec l'année, le nombre de pages et le nom du fichier.
3. **Affichage en direct** de chaque rapport volumineux détecté (`📚 VOLUMINEUX | Entreprise | Année | Pages`).
4. **Calcul d'un résumé global** : nombre total de rapports analysés, nombre et pourcentage de rapports volumineux.
5. **Sauvegarde du résultat** dans `rapports_volumineux.json`.

## 4. Utilisation

```bash
python detect_volumineux_from_json.py
```

Aucun argument en ligne de commande : le fichier d'entrée (`rapport_pages.json`) et le seuil (`SEUIL_VOLUMINEUX = 20`) sont fixés en constantes en tête de fichier. Pour changer le seuil, il faut modifier directement la valeur de `SEUIL_VOLUMINEUX` dans le code.

## 5. Sortie produite

**`rapports_volumineux.json`**, avec la structure suivante :

```json
{
  "seuil": 20,
  "total_rapports": 350,
  "total_volumineux": 87,
  "rapports_volumineux": {
    "MANAGEM": [
      {"annee": "2018", "pages": 330, "fichier": "2018.pdf"},
      ...
    ],
    ...
  }
}
```

C'est ce fichier qui sert directement d'entrée à `smart_scrape_batch.py` (paramètre `--json`) et à `classify_scanned_vs_text.py`.

## 6. Résumé affiché en console

```
Total rapports analysés   : 350
Rapports volumineux       : 87 (24.9%)
Seuil utilisé             : 20 pages
```

## 7. Limites connues

- Le seuil est codé en dur dans le fichier (`SEUIL_VOLUMINEUX = 20`) plutôt qu'exposé en argument de ligne de commande — toute modification nécessite d'éditer le script directement (contrairement à `classify_scanned_vs_text.py`, qui expose un `--seuil-pages` équivalent).
- Le script ne filtre pas les rapports dont le comptage de pages a échoué (`pages == -1`, cf. limites de `count_pdf_pages.py`) : un tel rapport ne sera jamais détecté comme volumineux (car `-1 < 20`), ce qui peut masquer silencieusement un problème de lecture en amont.
- Aucune notion de "hors périmètre" (ex. banques, sociétés étrangères) n'est appliquée ici, contrairement au script de validation comptable avancée vu précédemment — tous les rapports sont traités de la même façon.
