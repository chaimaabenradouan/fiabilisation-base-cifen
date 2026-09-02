# Documentation — `08_appliquer_remplacements.py` (anciennement apply_replacements.py)

## 1. Rôle dans le pipeline

C'est le **seul script de tout le pipeline qui touche réellement au dossier `Rapports/`**. Tous les scripts précédents (`smart_scrape_batch.py`, `verify_candidates_quality.py`, `generate_replacement_decisions.py`, `rescue_excluded_candidates.py`) ne font que **proposer** des candidats et des décisions, sans jamais modifier les originaux. Celui-ci exécute (ou simule) le remplacement final.

## 2. Les 4 garanties de sécurité

Le script est conçu pour être aussi sûr que possible :

1. **`--dry-run` actif par défaut** : rien n'est modifié tant que l'option `--execute` n'est pas explicitement passée. Chaque exécution sans `--execute` n'est qu'une **simulation**.
2. **Sauvegarde systématique avant remplacement** : chaque original remplacé est **déplacé** (jamais supprimé) vers `Rapports_backup_originaux/<ENTREPRISE>/<ANNEE>.pdf`, qui reproduit exactement la structure de `Rapports/`. Rien n'est perdu.
3. **Idempotence** : si un original a déjà été sauvegardé lors d'une exécution précédente, il n'est **pas re-déplacé** lors d'une relance — cela évite d'écraser une sauvegarde existante (contenant le vrai original) par une version déjà remplacée.
4. **Rapport détaillé** de chaque action, affiché en console et sauvegardé dans un CSV.

## 3. Entrée attendue

Le fichier `REPLACEMENT_DECISIONS.csv` (produit par `generate_replacement_decisions.py`, éventuellement édité manuellement). **Seules les lignes avec `Action == "remplacer"` sont traitées** ; les autres sont ignorées.

## 4. Fonctionnement étape par étape (`process_row`, pour chaque ligne "remplacer")

1. Vérification que le **fichier candidat** existe (sinon → statut `ERREUR`).
2. Vérification que l'**original** existe dans `Rapports/<ENTREPRISE>/<ANNEE>.pdf` (sinon → statut `ERREUR`).
3. **Si mode simulation** (`--dry-run`, par défaut) : affiche ce qui *serait* fait, sans rien modifier réellement → statut `SIMULE`.
4. **Si mode exécution** (`--execute`) :
   - Si l'original n'a jamais été sauvegardé → il est **déplacé** vers `Rapports_backup_originaux/`.
   - Si l'original a déjà été sauvegardé lors d'un run précédent → la sauvegarde existante n'est **pas touchée** ; le fichier courant dans `Rapports/` est simplement supprimé avant d'être remplacé.
   - Le candidat est **copié** (pas déplacé) vers `Rapports/<ENTREPRISE>/<ANNEE>.pdf`.
   - Statut final → `REMPLACE`.

## 5. Utilisation

```bash
# 1) TOUJOURS commencer par une simulation (rien n'est modifié)
python apply_replacements.py

# 2) Une fois la simulation vérifiée, exécuter pour de vrai
python apply_replacements.py --execute
```

| Argument | Description | Défaut |
|---|---|---|
| `--decisions` | Fichier de décisions à appliquer | `smart_test_output/REPLACEMENT_DECISIONS.csv` |
| `--rapports-dir` | Dossier des rapports originaux | `Rapports` |
| `--backup-dir` | Dossier de sauvegarde des originaux remplacés | `Rapports_backup_originaux` |
| `--report` | Fichier de rapport des actions effectuées | `smart_test_output/APPLY_REPORT.csv` |
| `--execute` | Applique réellement les changements. **Sans ce flag, simulation uniquement.** | Désactivé (dry-run) |

## 6. Sorties produites

| Fichier | Contenu |
|---|---|
| `Rapports/<ENTREPRISE>/<ANNEE>.pdf` | Remplacé par le candidat (uniquement si `--execute`) |
| `Rapports_backup_originaux/<ENTREPRISE>/<ANNEE>.pdf` | L'original sauvegardé, intouché |
| `smart_test_output/APPLY_REPORT.csv` | Rapport détaillé de chaque action (statut, gain de pages) |

Le rapport contient, pour chaque ligne traitée : le nombre de pages avant/après, le statut (`REMPLACE` / `SIMULE` / `ERREUR`), et un détail textuel de l'action effectuée (ou qui aurait été effectuée en simulation).

## 7. Résumé affiché en fin d'exécution

- En mode simulation : nombre de remplacements **prévus**, nombre d'erreurs détectées, rappel d'utiliser `--execute` pour appliquer réellement.
- En mode exécution : nombre de fichiers **effectivement remplacés**, nombre d'erreurs, **gain total de pages** (utile pour estimer le temps gagné en traitement ultérieur, ex. par MinerU), et rappel de l'emplacement des sauvegardes.

## 8. Limites connues

- Le script suppose que le nom de fichier de l'original suit exactement le format `<ANNEE>.pdf` dans `Rapports/<ENTREPRISE>/` — toute autre convention de nommage nécessiterait une adaptation.
- En cas d'erreur pendant la copie (ex. disque plein, permissions), le script rapporte l'erreur mais ne fait pas de rollback automatique de l'étape de sauvegarde déjà effectuée — il faut alors vérifier manuellement l'état du dossier concerné avant de relancer.
- Il n'y a pas de vérification d'intégrité du fichier candidat après copie (ex. re-comptage des pages) : la confiance repose sur les vérifications faites en amont par les scripts précédents.
