# 03_recuperation_annees_manquantes_bourse.py — Rattrapage intelligent des rapports manquants (v5)

## Objectif

À partir d'un fichier listant les entreprises ayant des années manquantes
(produit par le script d'analyse des années manquantes), retourner sur le
site de la Bourse de Casablanca pour tenter de télécharger spécifiquement
les rapports **manquants**, avec une détection élargie de types de documents
(annuel, semestriel, trimestriel) et une pagination plus robuste que la
version précédente.

## Arborescence et configuration

Le script utilise des chemins calculés à partir de la position du fichier
(`PROJECT_ROOT = Path(__file__).resolve().parents[2]`) et crée automatiquement
toute l'arborescence nécessaire au démarrage :

```
data/
├── raw/                (dossier de sortie des PDF, un sous-dossier par entreprise)
├── interim/
├── processed/
├── archive/
outputs/
logs/
backup/
```

| Fichier | Rôle |
|---|---|
| `data/rapports_metadata.csv` | Métadonnées cumulées de tous les rapports (mise à jour, jamais écrasée) |
| `data/liste_emetteurs.csv` | Table de correspondance nom d'entreprise → URL de fiche |
| `data/annees_manquantes_*.csv` | Fichier(s) d'entrée listant les entreprises incomplètes |
| `logs/fill_missing_v5.log` | Log détaillé de l'exécution |
| `backup/rapports_metadata_backup_<timestamp>.csv` | Sauvegarde du CSV de métadonnées avant modification |

`START_YEAR = 2016`, `CURRENT_YEAR = 2026` définissent la plage d'années valides.

## Détection élargie des types de documents

Trois listes de mots-clés, classées par priorité :

- `KEYWORDS_ANNUAL` : rapport annuel, RFA, rapport intégré, rapport de
  gestion, rapport d'activité, états financiers, états de synthèse, comptes
  annuels, comptes consolidés, document de référence, document
  d'enregistrement universel, communication financière annuelle, annual
  report, financial statements, consolidated financial statements.
- `KEYWORDS_SEMESTRIAL` : rapport semestriel, rapport financier semestriel,
  rapport intermédiaire, half year, h1/h2/s1/s2.
- `KEYWORDS_QUARTERLY` : rapport trimestriel, résultats trimestriels,
  q1-q4, t1-t4, quarterly report.

### `score_document(title)`

1. Parcourt `KEYWORDS_ANNUAL` dans l'ordre : si un mot-clé est trouvé dans le
   titre, le score est `100 - index_du_mot_clé * 5` (les premiers mots-clés de
   la liste sont donc considérés comme les plus fiables).
2. Si aucun score annuel n'a été trouvé (`best_score == 0`), cherche dans
   `KEYWORDS_SEMESTRIAL` → score fixe de 70.
3. Si toujours rien, cherche dans `KEYWORDS_QUARTERLY` → score fixe de 50.
4. Retourne `(score, type_détecté)`.

Contrairement au script Phase 2, ce script ne filtre **pas** les documents par
un score minimum au moment de la collecte : le filtrage se fait ensuite par
correspondance sur l'année manquante recherchée.

## Pagination robuste (`get_all_publication_pages`)

Version renforcée par rapport à la Phase 2, avec plusieurs mécanismes
anti-boucle et de diagnostic :

1. À chaque page, calcule un hash partiel du HTML (`hash(html_before[:5000])`)
   et le compare à l'ensemble des hashs déjà vus (`visited_hashes`) : si un
   hash déjà vu réapparaît, la pagination est considérée comme bouclée et le
   parcours s'arrête.
2. Logue le nombre de PDF détectés par page, ainsi que le titre du premier et
   du dernier PDF de la page, pour faciliter le diagnostic en cas de blocage.
3. Pour chaque lien PDF : extrait titre, URL, score/type (`score_document`),
   et année (regex sur le titre **et** l'URL du PDF, plus permissif que la
   Phase 2 qui ne regardait que le titre).
4. Pagination : localise le bouton "suivant" (`button.rounded-full`, `a[rel='next']`
   ou `li.next`), scrolle la page jusqu'en bas avant de cliquer (pour
   s'assurer que le bouton est bien cliquable), clique, attend
   `networkidle` puis un court délai fixe.
5. Après le clic, revérifie le hash du nouveau contenu : si identique au
   précédent, la pagination s'arrête (le clic n'a rien changé).
6. Sécurité anti-boucle infinie : `max_pages = 100`.

## Rattrapage intelligent (partie v5)

### `get_latest_missing_csv()`

Cherche dans `data/` tous les fichiers correspondant au motif
`annees_manquantes_*.csv` et retourne le plus récent (par date de modification).

### `create_backup()`

Si `rapports_metadata.csv` existe déjà, en fait une copie horodatée dans
`backup/` avant toute modification.

### `main()`

1. Crée la sauvegarde de sécurité (`create_backup`).
2. Charge le CSV d'années manquantes le plus récent, ne garde que les lignes
   où `Nb_Annees_Manquantes > 0`.
3. Si aucune entreprise incomplète : log et arrêt immédiat.
4. Charge la table de correspondance `liste_emetteurs.csv` (nom → URL de fiche).
5. Ouvre le navigateur Playwright.
6. Pour chaque entreprise incomplète (boucle `tqdm`) :
   - parse la liste des années manquantes depuis la colonne `Annees_Manquantes`
     (chaîne séparée par des virgules) ;
   - résout l'URL de la fiche via la table de correspondance ; si absente,
     enregistre un statut `URL introuvable` et passe à l'entreprise suivante ;
   - ouvre la section publications (`open_publications_section`) ;
   - collecte tous les documents disponibles (`get_all_publication_pages`) ;
   - sélectionne le meilleur document par année (`select_best_per_year`) ;
   - pour chaque année manquante demandée :
     - si un document existe pour cette année → téléchargement
       (`download_pdf`) dans `data/raw/<entreprise>/<annee>.pdf`, ajout aux
       métadonnées et au suivi (`followup`) avec statut `Succès` ;
     - sinon → statut `Introuvable` dans le suivi.
   - toute exception sur une entreprise est capturée, loguée, et enregistrée
     dans le suivi sans interrompre le traitement des autres entreprises.
7. Ferme le navigateur (bloc `finally`).
8. **Fusion des métadonnées** : si de nouveaux rapports ont été trouvés, les
   combine avec le CSV existant (`pd.concat`), déduplique sur `Chemin_Local`,
   et réécrit `rapports_metadata.csv`.
9. Sauvegarde le suivi détaillé (succès/échecs par entreprise/année) dans
   `data/rapports_recuperes.csv`.
10. Prévoit un ré-appel automatique du script de vérification des années
    manquantes (ligne commentée, non activée par défaut).

## Téléchargement (`download_pdf`)

Identique dans son principe à la Phase 2 : requête HTTP via le contexte
Playwright, écriture directe des octets sur disque, retourne `True`/`False`.
Si le fichier de destination existe déjà, retourne `True` sans re-télécharger.

## Dépendances

- `playwright` (synchrone, navigateur Chromium visible)
- `beautifulsoup4`
- `pandas`
- `tqdm`

## Fichiers produits / modifiés

```
data/raw/<Entreprise>/<Annee>.pdf
data/rapports_metadata.csv      (mis à jour, avec backup préalable)
data/rapports_recuperes.csv     (suivi détaillé de cette exécution)
logs/fill_missing_v5.log
backup/rapports_metadata_backup_<timestamp>.csv
```
