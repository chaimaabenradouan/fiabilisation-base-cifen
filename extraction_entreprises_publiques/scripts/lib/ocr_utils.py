
"""
ocr_utils.py
================================================================================
Fonctions OCR de base, réutilisées par les 3 extracteurs de tableaux.
100% gratuit / local : Tesseract OCR (apt: tesseract-ocr, tesseract-ocr-fra)
+ pytesseract (pip). Aucune dépendance à une API payante.

Principe retenu (après tests) :
- PAS de "table structure recognition" (Docling / PP-Structure / Table
  Transformer) : ces modèles attendent une vraie grille à bordures nettes.
  Cette fiche EEP est un FORMULAIRE (cellules label/valeur fusionnées,
  labels sur 1 à 3 lignes, colonne arabe collée à côté) -> ces modèles
  fusionnent/cassent les champs de façon imprévisible.
- OCR mot-à-mot avec coordonnées (image_to_data), puis ANCRAGE PAR
  MOT-CLÉ : on cherche la position de chaque libellé connu, et on prend
  tout ce qui se trouve à droite, dans la même bande verticale -- peu
  importe si le libellé fait 1 ou 3 lignes. C'est ce qui rend le script
  robuste aux variations d'une entreprise à l'autre.
"""

import re
import unicodedata
from PIL import Image
import pytesseract
from pytesseract import Output
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def normalize(text: str) -> str:
    """Minuscule, sans accents, espaces normalisés -- pour comparer un mot
    OCR à un mot-clé de référence sans se soucier des accents/majuscules."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def strip_arabic(text: str) -> str:
    """Enlève les caractères arabes qui ont pu 'baver' dans la zone
    française à cause d'un recadrage un peu trop large."""
    return re.sub(r"\s+", " ", ARABIC_RE.sub(" ", text)).strip()


def ocr_words(img: Image.Image, box, upscale: float = 1.5, psm: int = 11, lang: str = "fra"):
    """OCR une zone rectangulaire de l'image pleine page.

    Retourne une liste de dicts {left, top, height, width, text} en
    coordonnées ABSOLUES (relatives à l'image originale, pas au crop),
    ce qui permet de comparer/combiner des résultats entre plusieurs
    appels sans se perdre dans les systèmes de coordonnées.

    upscale=1.5 est un bon compromis : suffisant pour que Tesseract lise
    correctement les petits nombres, sans être si gros que le seuillage
    interne de Tesseract commence à abîmer l'anti-aliasing.
    psm=11 (texte épars, ordre non garanti) est le mode le plus robuste
    pour un formulaire où le texte est dispersé dans des cases, pas dans
    un flux de paragraphe classique.
    """
    x0, y0, x1, y1 = box
    zone = img.crop((x0, y0, x1, y1)).convert("L")
    w, h = zone.size
    zone = zone.resize((int(w * upscale), int(h * upscale)), Image.LANCZOS)

    data = pytesseract.image_to_data(zone, lang=lang, config=f"--psm {psm}", output_type=Output.DICT)

    words = []
    n = len(data["text"])
    for i in range(n):
        t = data["text"][i].strip()
        if not t:
            continue
        # reconversion vers coordonnées absolues de la page originale
        left = x0 + data["left"][i] / upscale
        top = y0 + data["top"][i] / upscale
        width = data["width"][i] / upscale
        height = data["height"][i] / upscale
        words.append({"left": left, "top": top, "width": width, "height": height, "text": t})
    return words


def cluster_lines(words, y_tolerance: float = 12):
    """Regroupe une liste de mots (avec coordonnées absolues) en lignes
    visuelles, en fonction de leur centre vertical. Retourne une liste
    de lignes triées top->bottom, chaque ligne étant elle-même triée
    left->right : [{'cy': ..., 'words': [(left, text), ...]}, ...]
    """
    words_sorted = sorted(words, key=lambda w: w["top"])
    lines = []
    for w in words_sorted:
        cy = w["top"] + w["height"] / 2
        for line in lines:
            if abs(line["cy"] - cy) < y_tolerance:
                line["words"].append(w)
                break
        else:
            lines.append({"cy": cy, "words": [w]})
    for line in lines:
        line["words"].sort(key=lambda w: w["left"])
    return sorted(lines, key=lambda l: l["cy"])


def line_text(line) -> str:
    return strip_arabic(" ".join(w["text"] for w in line["words"]))