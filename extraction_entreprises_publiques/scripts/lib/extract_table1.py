"""
extract_table1.py — lecture OCR, sans whitelist de valeurs
================================================================================
- Plus de KNOWN_CLASSIFICATIONS / KNOWN_CATEGORIES en tant que whitelist dure :
  elles ne servent plus qu'a UNE correction Levenshtein optionnelle (voir plus
  bas), le texte lu reste toujours affiche si aucune correspondance proche.
- classification_juridique et categorie = texte lu dans la bande, nettoye
  (puis corrige seulement si tres proche d'une valeur connue du gabarit)
- capital : fusion espace milliers (structurel typo FR)
- sigle : nettoyage structurel (pas de noms d'entreprises)
"""

import re
from collections import Counter
from extraction_entreprises_publiques.scripts.lib.ocr_utils import ocr_words, normalize, strip_arabic, cluster_lines

FIELD_KEYWORDS = {
    "sigle": ["sigle"],
    "capital_social": ["capital", "social"],
    "date_creation": ["date", "creation"],
    "classification_juridique": ["classification", "juridique"],
    "activite": ["activite"],
    "categorie": ["categorie"],
    "participation_totale": ["totale"],
    "participation_directe": ["directe"],
    "participation_indirecte": ["indirecte"],
}

# mots generiques de mise en page / unites — PAS des valeurs metier
NOISE_WORDS = {
    "millions", "de", "dh", "mdh", "dirhams", "en",
    "classification", "juridique", "categorie", "activite",
    "capital", "social", "date", "creation", "sigle",
    "participation", "publique", "totale", "directe", "indirecte",
}

MAX_BAND_HALF_HEIGHT = 130
CROP_WIDTHS = [0.58, 0.72, 0.85]

SIGLE_STOP = {
    "sigle", "maison", "mere", "groupe", "millions", "dh", "mdh",
    "a", "verifier",
}

# --- AJOUT (correction Levenshtein verifiee) --------------------------------
# Vocabulaire FERME du gabarit (pas des donnees d'entreprise -- ces valeurs
# sont les seules possibles pour ces 2 champs sur tout le document, c'est une
# propriete du FORMULAIRE, comme un menu deroulant a choix fixes). Utilise
# uniquement pour CORRIGER un texte deja lu s'il est tres proche -- jamais
# pour remplacer un texte qui ne correspond a rien.
KNOWN_CLASSIFICATIONS = [
    "FILIALE PUBLIQUE", "ETABLISSEMENT PUBLIC", "SOCIETE D'ETAT",
]
KNOWN_CATEGORIES = [
    "MARCHAND", "NON MARCHAND", "INSTITUTION FINANCIERE PUBLIQUE",
    "ORGANISME SOCIAL", "COMMERCIAL",
]


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def _fuzzy_correct(text: str, known_values, max_rel_distance: float = 0.25) -> str:
    """Corrige contre le vocabulaire FERME du gabarit si assez proche,
    sinon renvoie le texte brut tel quel (jamais de correction forcee a
    l'aveugle -- on prefere un texte imparfait visible plutot qu'une
    correction hasardeuse et invisible)."""
    if not text:
        return text
    text_norm = normalize(text)
    best_val, best_dist = None, None
    for val in known_values:
        d = _levenshtein(text_norm, normalize(val))
        if best_dist is None or d < best_dist:
            best_val, best_dist = val, d
    if best_val is not None and best_dist / max(len(best_val), 1) <= max_rel_distance:
        return best_val
    return text
# --- FIN AJOUT ---------------------------------------------------------------


def _is_garbage_token(text: str) -> bool:
    if len(text) > 25:
        return True
    if re.search(r"(.)\1{4,}", text):
        return True
    return False


def _looks_like_arabic_bleed(raw_text: str) -> bool:
    letters = [c for c in raw_text if c.isalpha()]
    if not letters:
        return False
    return any(c.islower() for c in letters)


def _is_noise(word_norm: str) -> bool:
    if len(word_norm) <= 1:
        return True
    stripped = word_norm.strip("_.")
    return stripped in NOISE_WORDS


def _extract_date(raw_band_text: str) -> str:
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})", raw_band_text)
    if not m:
        return ""
    d, mth, y = m.groups()
    if len(y) == 2:
        y = "19" + y if int(y) > 30 else "20" + y
    elif len(y) == 3:
        y = "1" + y
    d, mth, y = int(d), int(mth), int(y)
    if not (1 <= d <= 31 and 1 <= mth <= 12 and 1900 <= y <= 2030):
        return ""
    return f"{d:02d}/{mth:02d}/{y}"


def _merge_capital_spaces(text: str) -> str:
    """Recolle '2 104,0' / '12 304,8' (espace milliers FR)."""
    def repl(m):
        return m.group(1) + m.group(2) + (m.group(3) or "")

    prev, cur = None, text
    while prev != cur:
        prev = cur
        cur = re.sub(
            r"(?<![A-Za-z0-9])(\d{1,2})\s+(\d{3})([.,]\d+)?(?![A-Za-z0-9])",
            repl,
            cur,
        )
    return cur


def _best_capital(raw_band_text: str) -> str:
    text = _merge_capital_spaces(raw_band_text)
    candidates = re.findall(r"(?<![A-Za-z])\d(?:[\d .,]*\d)?(?![A-Za-z])", text)
    candidates = [c.strip() for c in candidates if c.strip()]
    if not candidates:
        return ""
    best = max(candidates, key=lambda c: len(re.sub(r"\s", "", c)))
    best = re.sub(r"\s+", "", best)
    if "," in best or "." in best:
        sep = "," if "," in best else "."
        integer_part, _, decimal_part = best.partition(sep)
    else:
        integer_part, decimal_part = best, None
    integer_part = integer_part.lstrip("0") or "0"
    groups = []
    while len(integer_part) > 3:
        groups.insert(0, integer_part[-3:])
        integer_part = integer_part[:-3]
    groups.insert(0, integer_part)
    formatted = " ".join(groups)
    if decimal_part is not None:
        formatted += "," + decimal_part
    return formatted


def _clean_text_field(raw: str, max_len: int = 100) -> str:
    """Nettoie un champ texte LU (classification, categorie, activite)."""
    if not raw:
        return ""
    parts = []
    for p in raw.split():
        n = normalize(p)
        if n in NOISE_WORDS:
            continue
        if _is_garbage_token(p) or _looks_like_arabic_bleed(p):
            continue
        if re.fullmatch(r"[\d.,/%\-]+", p):
            continue
        parts.append(p)
    text = " ".join(parts).strip(" ,;|-_")
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text


def _clean_sigle(raw: str) -> str:
    if not raw:
        return ""
    parts = re.split(r"[\s|/]+", raw.strip())
    kept = []
    for p in parts:
        p = p.strip("()[].,;:")
        if not p:
            continue
        n = normalize(p)
        if n in SIGLE_STOP or "maison" in n:
            break
        if re.fullmatch(r"\d+", p):
            continue
        if not re.search(r"[A-Za-z]", p):
            continue
        if len(p) > 20:
            continue
        kept.append(p)
    sigle = " ".join(kept).strip()
    if len(sigle) > 40 and kept:
        for p in kept:
            if p.isupper() or len(p) <= 12:
                return p
        return kept[0]
    return sigle


def _locate_sigle_top(img, y_search_end: float, x_frac_end: float) -> float:
    w, _ = img.size
    words = ocr_words(
        img, (0, 0, int(x_frac_end * w), int(y_search_end)), upscale=1.6, psm=11
    )
    for wd in words:
        if normalize(wd["text"]) == "sigle":
            return wd["top"]
    return 0.0


def _extract_sigle_dedicated(img, sigle_top: float, x_frac_end: float) -> str:
    if sigle_top <= 0:
        return ""
    w, _ = img.size
    box = (0, int(sigle_top - 40), int(x_frac_end * w), int(sigle_top + 120))
    words = ocr_words(img, box, upscale=1.6, psm=11)
    value_words = []
    for wd in words:
        if not (sigle_top - 15 <= wd["top"] <= sigle_top + 35):
            continue
        t = strip_arabic(wd["text"]).strip()
        if not t or _is_garbage_token(t) or _looks_like_arabic_bleed(t):
            continue
        if normalize(t) == "sigle":
            continue
        if not re.search(r"[A-Za-z0-9]", t):
            continue
        value_words.append(wd)
    value_words.sort(key=lambda wd: wd["left"])
    return _clean_sigle(" ".join(wd["text"] for wd in value_words))


def _single_pass(img, y_start: float, y_end: float, x_frac_end: float) -> dict:
    w, h = img.size
    box = (0, int(y_start), int(x_frac_end * w), int(y_end))
    words = ocr_words(img, box, upscale=1.6, psm=11)

    clean_words = []
    for wd in words:
        t = strip_arabic(wd["text"]).strip()
        if t and not _is_garbage_token(t):
            clean_words.append({**wd, "text": t, "norm": normalize(t)})

    field_centers = {}
    label_word_ids = set()
    for field, keywords in FIELD_KEYWORDS.items():
        centers = []
        for i, wd in enumerate(clean_words):
            if any(kw == wd["norm"] or wd["norm"].startswith(kw) for kw in keywords):
                centers.append(wd["top"] + wd["height"] / 2)
                label_word_ids.add(i)
        if centers:
            field_centers[field] = sum(centers) / len(centers)

    ordered = sorted(field_centers.items(), key=lambda kv: kv[1])
    field_bands = {}
    for idx, (field, cy) in enumerate(ordered):
        prev_cy = ordered[idx - 1][1] if idx > 0 else y_start
        next_cy = ordered[idx + 1][1] if idx < len(ordered) - 1 else y_end
        y0 = max((prev_cy + cy) / 2, cy - MAX_BAND_HALF_HEIGHT)
        y1 = min((cy + next_cy) / 2, cy + MAX_BAND_HALF_HEIGHT)
        field_bands[field] = (y0, y1)

    raw_values = {}
    for field, (y0, y1) in field_bands.items():
        value_words = []
        for i, wd in enumerate(clean_words):
            if i in label_word_ids:
                continue
            cy = wd["top"] + wd["height"] / 2
            if field.startswith("participation_") and wd["norm"] in (
                "participation",
                "publique",
            ):
                continue
            if (
                y0 <= cy <= y1
                and not _is_noise(wd["norm"])
                and not _looks_like_arabic_bleed(wd["text"])
            ):
                value_words.append(wd)
        value_words.sort(key=lambda wd: wd["left"])
        value_lines = cluster_lines(value_words, y_tolerance=12)
        raw_values[field] = " ".join(
            " ".join(wd["text"] for wd in line["words"]) for line in value_lines
        ).strip()

    return raw_values


def _sigle_fallback_pass(img, y_end: float, x_frac_end: float) -> str:
    sigle_top = _locate_sigle_top(img, y_end, x_frac_end)
    if sigle_top <= 0:
        return ""
    y_start = max(0, sigle_top - 130)
    raw = _single_pass(img, y_start, y_end, x_frac_end)
    return _clean_sigle(raw.get("sigle", "").strip())


def extract_table1(img, y_start: float, y_end: float, x_frac_end: float = None) -> dict:
    widths = [x_frac_end] if x_frac_end is not None else CROP_WIDTHS
    passes = [_single_pass(img, y_start, y_end, w) for w in widths]

    result = {}

    # sigle : premiere passe non vide, nettoyee
    result["sigle"] = ""
    for p in passes:
        val = _clean_sigle(p.get("sigle", "").strip())
        if val:
            result["sigle"] = val
            break
    if not result["sigle"]:
        for w in CROP_WIDTHS:
            result["sigle"] = _sigle_fallback_pass(img, y_end, w)
            if result["sigle"]:
                break
    if not result["sigle"]:
        st = _locate_sigle_top(img, y_end, CROP_WIDTHS[-1])
        result["sigle"] = _extract_sigle_dedicated(img, st, CROP_WIDTHS[-1])

    # activite / classification / categorie : TEXTE LU, pas de whitelist
    for field, max_len in (
        ("activite", 120),
        ("classification_juridique", 60),
        ("categorie", 40),
    ):
        result[field] = ""
        for p in passes:
            val = _clean_text_field(p.get(field, ""), max_len=max_len)
            if val:
                result[field] = val
                break
        # --- AJOUT (correction Levenshtein verifiee) ---
        # activite exclue : texte libre, ne doit jamais etre force vers une
        # valeur predefinie. Seuls classification_juridique et categorie
        # passent par le vocabulaire ferme du gabarit, et seulement s'ils
        # sont deja tres proches d'une valeur connue.
        if field == "classification_juridique" and result[field]:
            result[field] = _fuzzy_correct(result[field], KNOWN_CLASSIFICATIONS)
        elif field == "categorie" and result[field]:
            result[field] = _fuzzy_correct(result[field], KNOWN_CATEGORIES)
        # --- FIN AJOUT ---

    # date
    dates = [_extract_date(p.get("date_creation", "")) for p in passes]
    dates = [d for d in dates if d]
    result["date_creation"] = Counter(dates).most_common(1)[0][0] if dates else ""

    # capital
    capitals = [_best_capital(p.get("capital_social", "")) for p in passes]
    capitals = [c for c in capitals if c]
    result["capital_social"] = (
        max(capitals, key=lambda c: len(re.sub(r"\s", "", c))) if capitals else ""
    )

    # participation %
    for field in (
        "participation_totale",
        "participation_directe",
        "participation_indirecte",
    ):
        pct_matches = []
        for p in passes:
            m = re.search(r"\d{1,3}(?:[.,]\d+)?\s*%", p.get(field, ""))
            if m:
                pct_matches.append(m.group().replace(" ", ""))
        result[field] = (
            Counter(pct_matches).most_common(1)[0][0] if pct_matches else ""
        )

    return result