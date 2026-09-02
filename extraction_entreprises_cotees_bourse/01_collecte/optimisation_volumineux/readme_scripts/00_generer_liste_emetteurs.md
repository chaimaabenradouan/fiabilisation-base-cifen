# Documentation — `00_generer_liste_emetteurs.py` (anciennement generate_emetteurs.py)

## 1. Rôle dans le pipeline

C'est le **point de départ** de toute la chaîne de collecte : ce script scrape le site [casablanca-bourse.com](https://www.casablanca-bourse.com) pour construire la **liste de référence de tous les émetteurs cotés** (nom + lien vers leur fiche), sauvegardée dans `liste_emetteurs.csv`. Ce fichier est ensuite utilisé par tous les scripts en aval (notamment `smart_scrape_batch.py`) pour retrouver la page de chaque entreprise.

## 2. Problème résolu (bug corrigé en v2)

La version précédente s'arrêtait **silencieusement** à la page 4 de la liste des émetteurs, sans aucune erreur visible, en perdant des entreprises entières (ex. BMCI). La cause : au-delà d'environ 4 pages, le site masque les numéros de page intermédiaires derrière des points de suspension `...` (ex. `1 2 3 4 ... 6`). Le script cherchait un bouton portant exactement le texte du numéro suivant (`"5"`), qui n'existe pas dans le DOM tant qu'on n'a pas cliqué sur `...`.

## 3. Stratégie de pagination robuste

Pour passer à la page suivante, le script essaie, **dans l'ordre**, trois méthodes (fonction `click_next_page`) :

1. **Bouton numéroté exact**, s'il est directement visible dans le DOM.
2. **Flèche "suivant"** (`»`, `›`, ou `aria-label` contenant "Suivant"/"Next"), qui reste presque toujours visible même quand les numéros intermédiaires sont cachés.
3. **Clic sur les `...`** pour révéler les numéros cachés, puis clic sur le numéro suivant une fois révélé.

Si aucune de ces trois méthodes ne fonctionne, le script considère que la pagination est terminée.

## 4. Garde-fous anti-bug

- **Vérification de changement réel de contenu** : après chaque clic, le script compare la signature des noms d'entreprises affichés (`names_signature`) à celle de la page précédente. Si rien n'a changé, il considère qu'il est bloqué et **s'arrête proprement** avec un avertissement, plutôt que de boucler à l'infini ou de dupliquer des données.
- **`MAX_PAGES = 30`** : garde-fou de sécurité absolu, pour éviter une boucle infinie même en cas de comportement inattendu du site.
- **Déduplication par `URL_Fiche`** (et non simplement par nom) : si une même page est lue deux fois, l'entreprise n'est comptée qu'une seule fois dans le résultat final.

## 5. Fonctionnement étape par étape

1. **Ouverture du navigateur** (Playwright, Chromium, mode visible `headless=False` avec ralentissement `slow_mo=700` pour laisser le temps au site de réagir).
2. **Navigation** vers `casablanca-bourse.com/fr/listing-des-emetteurs`.
3. **Boucle de pagination** (jusqu'à `MAX_PAGES`) :
   - Extraction des lignes du tableau actuellement affiché (`extract_rows`) : nom de l'entreprise, URL de sa fiche, et un nom normalisé pour un usage en nom de dossier (`Folder_Name`, caractères interdits supprimés, espaces remplacés par `_`).
   - Ajout des nouvelles entreprises au dictionnaire global (dédupliqué par URL).
   - Tentative de passage à la page suivante via `click_next_page`.
   - Arrêt si aucun changement de contenu n'est détecté, ou si aucun bouton "suivant" n'est trouvé.
4. **Sauvegarde finale** dans `liste_emetteurs.csv` (colonnes : `Nom`, `URL_Fiche`, `Folder_Name`).

## 6. Fonctions clés

| Fonction | Rôle |
|---|---|
| `normalize_for_folder(name)` | Nettoie un nom d'entreprise pour qu'il soit utilisable comme nom de dossier (supprime les caractères interdits, remplace les espaces, limite à 120 caractères) |
| `extract_rows(page)` | Extrait les lignes du tableau HTML actuellement affiché |
| `get_visible_page_numbers(page)` | Liste tous les numéros de page visibles dans la barre de pagination (indicatif, pas forcément le nombre total réel si des `...` existent) |
| `click_next_page(page, current_page_num)` | Tente de passer à la page suivante avec la stratégie en 3 niveaux décrite en section 3 |
| `scrape_all_issuers()` | Fonction principale orchestrant tout le scraping |

## 7. Utilisation

```bash
python generate_emetteurs.py
```

Aucun argument en ligne de commande n'est prévu ; les paramètres (`BASE_URL`, `OUTPUT_CSV`, `MAX_PAGES`) sont définis en constantes en tête de fichier.

## 8. Sortie produite

**`liste_emetteurs.csv`**, avec les colonnes suivantes :

| Colonne | Description |
|---|---|
| `Nom` | Nom de l'entreprise tel qu'affiché sur le site |
| `URL_Fiche` | URL complète de la fiche émetteur |
| `Folder_Name` | Version normalisée du nom, utilisable comme nom de dossier |

## 9. Limites connues

- Le mode `headless=False` (navigateur visible) est nécessaire pour observer/déboguer le comportement, mais rend le script plus lent qu'un scraping "headless".
- La stratégie de pagination dépend de la structure HTML actuelle du site ; toute refonte du composant de pagination côté site nécessitera une adaptation des sélecteurs.
- Le script ne gère pas de reprise automatique en cas d'interruption en cours de route (contrairement à `smart_scrape_batch.py`, qui a un registre de progression) : en cas de coupure, il faut relancer depuis le début.
