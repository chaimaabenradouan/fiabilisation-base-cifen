"""
extract_table2.py -- version v3 (canonicalisation par liste blanche)
================================================================================
Changement de strategie par rapport aux versions precedentes : on arrete de
SLUGIFIER le texte OCR brut pour fabriquer les noms de colonnes (fragile : un
seul mot arabe mal OCRise en charabia latin se retrouvait concatene au nom
du champ, ex. "charges_d_exploitation_hd_euaosiall_cu").

A la place : liste blanche de ~15 champs CONNUS (observes sur les 19
entreprises). Chaque ligne du tableau est comparee a ces motifs par mots-cles
(pas par egalite exacte, pour tolerer l'ordre des mots et les mots en trop).
Des qu'un motif matche, on utilise le nom CANONIQUE fixe -- tout le reste du
texte de la ligne (charabia OCR, mots arabes mal reconnus...) est ignore
purement et simplement, jamais concatene.

Une ligne qui ne matche AUCUN motif connu est ignoree (loggee pour
transparence) plutot que de creer une colonne bruit.

Detection de la ligne d'en-tete : structurelle (ses tokens numeriques
ressemblent a des annees 19xx/20xx), pas textuelle (le mot "Indicateurs"
peut etre mal OCRise -- ex. "imticateurs" -- et rater un test de
sous-chaine).
"""

import re
from extraction_entreprises_publiques.scripts.lib.ocr_utils import ocr_words, normalize, cluster_lines, strip_arabic

print(">>> extract_table2.py VERSION v3 (canonicalisation) chargee <<<")

# --- Sous-sections connues (CNSS uniquement a ce jour) ----------------------
SECTION_HEADER_WHITELIST = [
    "regime general",
    "assurance maladie",
    "amo",
]


def _is_section_header(label_norm: str) -> bool:
    return any(pat in label_norm for pat in SECTION_HEADER_WHITELIST)


# --- Dictionnaire canonique des champs --------------------------------------
# Ordre = priorite (le premier motif qui matche gagne). Chaque motif est une
# liste de mots dont TOUS doivent apparaitre (en sous-chaine) dans le libelle
# normalise pour matcher.
CANONICAL_FIELDS = [
    ("cotisations_contributions", ["cotisation"]),
    ("pensions_prestations", ["pension"]),
    ("solde_technique", ["solde"]),
    ("charges_de_personnel", ["charges", "personnel"]),
    ("charges_exploitation_hd", ["charges", "exploitat"]),
    ("chiffre_affaires", ["chiffre"]),
    ("valeur_ajoutee", ["valeur", "ajout"]),
    ("impot_societes", ["impot"]),
    ("resultat_net", ["resultat"]),
    ("caf", ["caf"]),
    ("pnb", ["pnb"]),
    ("total_actif", ["total", "actif"]),
    ("fonds_propres", ["fonds", "propres"]),
    ("dettes_financement", ["dettes"]),
    ("investissements", ["investissement"]),
    ("effectif", ["effectif"]),
]


def _canonical_field(label_norm: str):
    """Retourne le nom canonique du champ, ou None si aucun motif connu ne
    correspond (ligne alors ignoree, pas de colonne bruit creee)."""
    for canonical, keywords in CANONICAL_FIELDS:
        if all(kw in label_norm for kw in keywords):
            # Cas particulier : "effectif"/"resultat_net" ont une variante
            # "du groupe" -- on la preserve, comme dans le schema d'origine.
            if canonical == "effectif" and "groupe" in label_norm:
                return "effectif_du_groupe"
            if canonical == "resultat_net" and "groupe" in label_norm:
                return "resultat_net_part_du_groupe"
            return canonical
    return None


def _clean_number(raw: str):
    raw = raw.replace(" ", "").replace("\u00a0", "")
    m = re.fullmatch(r"-?\d+(?:[.,]\d+)?", raw)
    if not m:
        return None
    return float(raw.replace(",", "."))


def _looks_like_year_tokens(tokens, min_ratio=0.5):
    """Detection STRUCTURELLE de la ligne d'en-tete : au moins la moitie de
    ses tokens numeriques ressemblent a une annee (19xx/20xx). Ne depend pas
    du texte du libelle (qui peut etre mal OCRise, ex. 'imticateurs')."""
    if not tokens:
        return False
    year_like = sum(1 for _, t, _ in tokens if re.fullmatch(r"(19|20)\d{2}", t))
    return year_like / len(tokens) >= min_ratio


def _cluster_columns(x_values, max_cols: int = 3, n_iter: int = 4):
    xs = sorted(set(x_values))
    if len(xs) <= 1:
        return [xs[0]] if xs else []
    gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
    gaps.sort(reverse=True)
    n_cuts = min(max_cols - 1, len(gaps))
    cut_indices = sorted(i for _, i in gaps[:n_cuts])
    bounds, start = [], 0
    for ci in cut_indices:
        bounds.append(xs[start:ci + 1])
        start = ci + 1
    bounds.append(xs[start:])
    centers = [sum(g) / len(g) for g in bounds if g]
    all_x = list(x_values)
    for _ in range(n_iter):
        groups = {i: [] for i in range(len(centers))}
        for x in all_x:
            idx = min(range(len(centers)), key=lambda i: abs(centers[i] - x))
            groups[idx].append(x)
        new_centers = [sum(g) / len(g) if g else centers[i] for i, g in groups.items()]
        if new_centers == centers:
            break
        centers = new_centers
    return sorted(centers)


def _guess_year_labels(header_tokens, n_cols):
    """FIX : on ne tente plus de lire les vraies annees (2022/2023/2024)
    depuis l'OCR de l'en-tete -- instable page par page (parfois lu,
    parfois non), ce qui produisait DEUX schemas de nommage differents
    selon les entreprises dans le meme CSV final (ex. "..._2023" pour
    l'une, "..._annee_2" pour l'autre -- illisible et non comparable).
    On utilise maintenant TOUJOURS les memes labels generiques, pour TOUTES
    les entreprises, garantissant un schema unique et coherent.
    A FAIRE UNE FOIS (pas par ce script) : verifier sur 1-2 entreprises
    connues (ex. ADM, CMR) quelle annee reelle correspond a annee_1/2/3,
    et documenter la correspondance ici en commentaire une fois confirmee."""
    return [f"annee_{i+1}" for i in range(n_cols)]


def extract_table2(img, y_start: float, y_end: float, x_frac_end: float = 0.75, n_cols: int = 3) -> dict:
    w, h = img.size
    box = (0, int(y_start), int(x_frac_end * w), int(y_end))
    words = ocr_words(img, box, upscale=1.6, psm=11)
    lines = cluster_lines(words, y_tolerance=14)

    rows = []
    header_tokens = None
    current_section = None

    for line in lines:
        label_words, tokens = [], []
        for wd in line["words"]:
            t = strip_arabic(wd["text"]).strip()
            if not t:
                continue
            if re.fullmatch(r"-?\d[\d.,]*", t):
                tokens.append((wd["left"] + wd["width"], t, wd["left"]))
            elif t.replace("'", "").isalpha():
                label_words.append(t)

        label = " ".join(label_words).strip()
        label_norm = normalize(label)

        # Detection d'en-tete STRUCTURELLE (priorite) + repli textuel
        if header_tokens is None and (_looks_like_year_tokens(tokens) or "indic" in label_norm):
            header_tokens = tokens
            continue

        if not tokens:
            if label and _is_section_header(label_norm):
                current_section = re.sub(r"[^a-z0-9]+", "_", label_norm).strip("_")
            elif label:
                print(f"      (ligne sans chiffre ignoree, non promue: {label!r})")
            continue

        canonical = _canonical_field(label_norm)
        if canonical is None:
            print(f"      (ligne ignoree, aucun champ connu ne correspond: {label!r})")
            continue

        rows.append((canonical, tokens, current_section))

    if not rows:
        return {}

    if header_tokens is not None and len(header_tokens) == n_cols:
        col_centers = sorted((x_right + x_left) / 2 for x_right, _, x_left in header_tokens)
    else:
        all_x = [x for _, tokens, _ in rows for x, _, _ in tokens]
        col_centers = sorted(_cluster_columns(all_x, max_cols=n_cols))

    def nearest_col(x):
        return min(range(len(col_centers)), key=lambda i: abs(col_centers[i] - x))

    year_labels = _guess_year_labels(header_tokens, len(col_centers))

    result = {}
    used_base_slugs = set()

    for canonical, tokens, section in rows:
        base_slug = f"{section}_{canonical}" if section else canonical

        if base_slug in used_base_slugs:
            dup_idx = 2
            candidate = f"{base_slug}_dup{dup_idx}"
            while candidate in used_base_slugs:
                dup_idx += 1
                candidate = f"{base_slug}_dup{dup_idx}"
            base_slug = candidate
        used_base_slugs.add(base_slug)

        by_col = {}
        for x_right, t, x_left in sorted(tokens, key=lambda p: p[2]):
            col = nearest_col(x_right)
            by_col.setdefault(col, []).append(t)
        for col, parts in by_col.items():
            val = _clean_number("".join(parts))
            if val is not None:
                result[f"{base_slug}_{year_labels[col]}"] = val

    return result