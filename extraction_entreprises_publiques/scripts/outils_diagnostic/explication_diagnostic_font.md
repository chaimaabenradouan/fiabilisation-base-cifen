# Documentation du script `diagnostic_font.py`

**Objectif** : Comprendre pourquoi le texte extrait d’un PDF ne correspond pas au texte affiché à l’écran, et déterminer si un mapping de caractères (cipher / police custom) est récupérable automatiquement.

**Auteur** : Script de diagnostic local  
**Dépendance** : `pymupdf` (`pip install pymupdf`)

---

## 1. Présentation générale

Ce script analyse un fichier PDF page par page (par défaut uniquement la première page) afin de diagnostiquer les problèmes d’extraction de texte. Il est particulièrement utile lorsque :

- Le texte extrait est illisible ou « brouillé »
- Le PDF utilise des polices personnalisées (custom fonts)
- Les caractères affichés ne correspondent pas aux codes Unicode extraits
- On suspecte l’absence (ou la présence) d’une table **ToUnicode**

Le script ne modifie jamais le PDF. Il se contente de lire les informations internes et d’afficher un rapport détaillé dans le terminal.

---

## 2. Utilisation

```bash
python diagnostic_font.py chemin/vers/exemple.pdf
```

**Exemple** :
```bash
python diagnostic_font.py mon_document.pdf
```

Le rapport s’affiche directement dans le terminal. Il peut être copié-collé pour analyse ultérieure (aucun envoi de fichier n’est nécessaire).

---

## 3. Structure du code

### 3.1 Imports

```python
import sys
import fitz  # pymupdf
import json
```

- `sys` : permet de récupérer le chemin du PDF passé en argument.
- `fitz` : bibliothèque PyMuPDF pour ouvrir et analyser les PDF.
- `json` : importé mais non utilisé dans la version actuelle (peut servir pour de futures extensions).

### 3.2 Fonction principale `diagnostic(pdf_path)`

```python
def diagnostic(pdf_path: str):
    doc = fitz.open(pdf_path)
```

Ouvre le PDF avec PyMuPDF.

#### a) Informations générales

```python
print(f"=== Diagnostic pour: {pdf_path} ===")
print(f"Nombre de pages: {len(doc)}\n")
```

Affiche le nom du fichier et le nombre total de pages.

#### b) Boucle sur les pages

```python
for page_num, page in enumerate(doc):
```

Parcourt les pages. **Par défaut, le script s’arrête après la première page** (voir `break` à la fin).

---

### 3.3 Analyse détaillée d’une page

#### 1. Texte brut extrait

```python
raw_text = page.get_text("text")
print(f"[Texte brut - 300 premiers caractères]:\n{raw_text[:300]}\n")
```

Extrait le texte tel que PyMuPDF le voit (mode `"text"`).  
Affiche uniquement les 300 premiers caractères pour garder le rapport lisible.

**Utilité** : Voir immédiatement si le texte extrait est correct ou « chiffré ».

---

#### 2. Liste des polices utilisées

```python
fonts = page.get_fonts(full=True)
```

Récupère toutes les polices embarquées dans la page avec le maximum d’informations.

Pour chaque police, le script affiche :
- `xref` : identifiant interne de l’objet police dans le PDF
- `type` : type de police (TrueType, Type1, etc.)
- `basefont` : nom de base de la police
- `name` : nom de la police
- `encoding` : encodage utilisé

Ensuite, il tente de détecter la présence d’une table **ToUnicode** :

```python
font_dict = doc.xref_object(xref, compressed=False)
has_tounicode = "ToUnicode" in font_dict
```

**Point critique** :  
La table `ToUnicode` est ce qui permet de faire correspondre les glyphes affichés aux vrais caractères Unicode.  
- Si elle est absente → le texte extrait sera souvent incorrect.  
- Si elle est présente → l’extraction a de bonnes chances de fonctionner correctement.

---

#### 3. Analyse caractère par caractère (partie la plus importante)

```python
text_dict = page.get_text("rawdict")
```

Utilise le mode `"rawdict"` qui donne accès à chaque caractère individuellement, avec sa police et son code.

Le script construit ensuite un dictionnaire :

```python
chars_seen.setdefault(key, set()).add((c, code))
```

où :
- `c` = caractère tel qu’extrait par PyMuPDF
- `code` = code Unicode (`ord(c)`)

**Résultat affiché** :  
Pour chaque police, un échantillon des 20 premiers couples `(caractère_extrait, code_unicode)`.

**Utilité** :  
Permet de voir exactement ce que PyMuPDF assigne à chaque glyphe.  
C’est la base pour détecter un éventuel « cipher » (mapping personnalisé entre codes et caractères affichés).

---

### 3.4 Limitation volontaire à la première page

```python
break
```

Le script s’arrête après la première page pour rester rapide et lisible.  
On peut facilement retirer ce `break` si l’on souhaite analyser toutes les pages.

---

### 3.5 Point d’entrée du script

```python
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python diagnostic_font.py chemin/vers/exemple.pdf")
        sys.exit(1)
    diagnostic(sys.argv[1])
```

Vérifie qu’un seul argument (le chemin du PDF) a été fourni, sinon affiche l’aide.

---

## 4. Interprétation des résultats

| Élément observé                     | Interprétation possible                                      |
|-------------------------------------|--------------------------------------------------------------|
| Texte brut illisible                | Probable absence de table ToUnicode ou police custom         |
| `ToUnicode: False`                  | La police n’a pas de mapping Unicode → extraction difficile  |
| Codes Unicode « bizarres »          | Possible cipher / encoding personnalisé                      |
| Même caractère extrait pour plusieurs glyphes | Mapping défectueux ou manquant                             |

---

## 5. Limites du script

- Analyse uniquement la première page par défaut.
- Ne reconstruit pas automatiquement le mapping cipher (il le détecte seulement).
- Ne gère pas les PDF protégés par mot de passe.
- Nécessite que `pymupdf` soit installé.

---

## 6. Évolutions possibles

- Analyser toutes les pages
- Extraire et sauvegarder la table ToUnicode si elle existe
- Tenter de reconstruire un mapping à partir des positions des glyphes
- Exporter le rapport en JSON ou Markdown
- Ajouter une détection automatique de polices « suspectes »

---

## 7. Conclusion

Ce script est un outil de **diagnostic local** destiné à comprendre les problèmes d’extraction de texte dans les PDF, notamment ceux utilisant des polices personnalisées.  
Il fournit les informations nécessaires pour décider si un traitement plus avancé (reconstruction de mapping, OCR, etc.) est nécessaire.

**Aucun fichier n’est envoyé à l’extérieur.** Tout le traitement reste sur la machine de l’utilisateur.
