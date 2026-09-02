"""
extract_table3.py -- Immo. corporelles
================================================================================
Structure DIFFERENTE des tableaux 1 et 2 : c'est une GRILLE 2x2 FIXE (pas une
liste verticale), toujours les 4 memes champs, dans le meme ordre visuel :

    Terrains                Constructions
    Installations tech.     Mobilier, Mat bureau

Chaque case = 1 libelle + 1 valeur juste en dessous (jamais au-dessus, jamais
tres loin). Approche generalisee (aucun nom d'entreprise, aucune valeur
codee en dur) :

1. Detecter les 4 libelles par mot-cle tolerant (1 mot distinctif suffit :
   "terrains", "constructions", "installations", "mobilier").
2. Assigner chaque token numerique au libelle le plus proche EN DESSOUS de
   lui (distance ponderee : priorite verticale, tolerance horizontale) --
   jamais a un libelle plus haut ou trop eloigne verticalement.
3. Nettoyer le nombre : dans CE tableau specifique, le separateur observe
   est un POINT tous les 3 chiffres (ex. "16.102" = 16102), pas une virgule
   decimale -- different des tableaux 1/2. Aucune decimale n'a ete observee
   dans Immo. corporelles.

Un "-" isole = valeur nulle/absente -> laisse vide (pas de fausse valeur 0
implicite, l'absence de donnee doit rester visible).
"""

import re
from extraction_entreprises_publiques.scripts.lib.ocr_utils import ocr_words, normalize, cluster_lines, strip_arabic

FIELD_KEYWORDS = {
    "terrains": ["terrains"],
    "constructions": ["constructions"],
    # Variante banques/institutions financieres (CAM, CDG...) : "Terrain &
    # construct." fusionne en UN seul champ au lieu de 2 separes.
    "terrain_construction": ["construct"],
    "installations_tech": ["installations"],
    "mobilier_mat_bureau": ["mobilier"],
    # Variante ONCF (materiel roulant au lieu de mobilier de bureau)
    "materiel_transport": ["materiel"],
    # Variante banques : "Equip. Mobilier & Inst." fusionne
    "equip_mobilier_inst": ["equip"],
    # Categories additionnelles specifiques a certaines institutions
    # financieres (CAM, CDG) -- decouvertes en analysant les 19 pages.
    # AJOUT : "location" en mot-cle alternatif -- le libelle complet est
    # "Droit d'utilisation des contrats de location" ; si l'OCR rate
    # "utilisation" (cas CAM observe), "location" reste un point d'ancrage
    # valide, sans collision avec aucun autre mot-cle de ce dict.
    "droit_utilisation_location": ["utilisation", "location"],
    "logiciel_acquis": ["logiciel"],
}

# Bruit specifique a ce petit tableau : unite / annee affichees en marge
# (texte pivote "2024" / "MDH" / "Millions de Dirham") -- gabarit, pas donnee.
NOISE_WORDS = {"mdh", "millions", "million", "de", "dirham", "dirhams", "dh"}

MAX_VALUE_DISTANCE_Y = 250  # eleve temporairement -- voir DEBUG ci-dessous


def _clean_number(raw: str):
    raw = raw.strip()
    if not raw or raw in ("-", "—", "–"):
        return None
    # "." ou "," suivi d'EXACTEMENT 3 chiffres = separateur de milliers dans
    # ce tableau (aucune decimale observee ici) -> on le retire.
    raw = re.sub(r"[.,](\d{3})(?!\d)", r"\1", raw)
    raw = raw.replace(" ", "")
    m = re.fullmatch(r"-?\d+(?:[.,]\d+)?", raw)
    if not m:
        return None
    return float(raw.replace(",", "."))


def extract_table3(img, y_start: float, y_end: float,
                    x_frac_start: float = 0.0, x_frac_end: float = 1.0) -> dict:
    w, h = img.size
    box = (int(x_frac_start * w), int(y_start), int(x_frac_end * w), int(y_end))
    print(f"      (DEBUG table3 - image {w}x{h}, boite utilisee: {box})")
    words = ocr_words(img, box, upscale=1.8, psm=11)
    print(f"      (DEBUG table3 - {len(words)} mots OCR bruts dans la boite)")
    if words:
        sample = [w["text"] for w in words[:20]]
        print(f"      (DEBUG table3 - echantillon: {sample})")

    clean_words = []
    for wd in words:
        t = strip_arabic(wd["text"]).strip()
        if not t:
            continue
        if normalize(t) in NOISE_WORDS:
            continue
        if re.fullmatch(r"(19|20)\d{2}", t):
            continue  # annee de reference en marge, pas une valeur du tableau
        clean_words.append({**wd, "text": t, "norm": normalize(t)})

    # 1) localiser les libelles -- UN SEUL passage sur les mots, priorite a
    # l'ordre du dict FIELD_KEYWORDS (le plus specifique en premier), pour
    # eviter qu'un mot-cle court (ex. "construct" pour la variante bancaire
    # fusionnee "Terrain & construct.") ne vole aussi le mot standard complet
    # "Constructions" deja revendique par le champ "constructions".
    label_positions = {}
    label_word_ids = set()
    for i, wd in enumerate(clean_words):
        for field, keywords in FIELD_KEYWORDS.items():
            if field in label_positions:
                continue  # deja trouve, ne pas ecraser
            if any(kw == wd["norm"] or wd["norm"].startswith(kw) for kw in keywords):
                cx = wd["left"] + wd["width"] / 2
                cy = wd["top"] + wd["height"] / 2
                label_positions[field] = (cx, cy)
                label_word_ids.add(i)
                break  # ce mot est pris, ne teste pas les autres champs dessus

    # --- AJOUT (dedoublonnage banniere fusionnee "Equip. Mobilier & Inst.") ---
    # BUG CONFIRME sur CAM : le mot "Mobilier" a l'interieur de la banniere
    # fusionnee "Equip. Mobilier & Inst." matche AUSSI, separement, le
    # mot-cle "mobilier" du champ standalone mobilier_mat_bureau -- creant un
    # FAUX second libelle quasiment a la meme position que
    # equip_mobilier_inst. L'algorithme glouton se retrouve alors avec deux
    # ancres presque identiques pour la meme bannniere, et peut assigner le
    # bon chiffre au mauvais des deux (observe : "72", la vraie valeur de
    # equip_mobilier_inst, colle a mobilier_mat_bureau ; "820", une valeur
    # d'un graphique voisin, colle a equip_mobilier_inst).
    # Fix : si les deux libelles sont trouves quasi au meme endroit (meme
    # ligne, proches horizontalement), c'est le signe d'une banniere
    # fusionnee mal scindee en deux -- on supprime le doublon
    # mobilier_mat_bureau et on garde equip_mobilier_inst comme ancre
    # unique. Ne s'applique jamais aux entreprises standard, ou
    # equip_mobilier_inst n'existe pas du tout.
    if "equip_mobilier_inst" in label_positions and "mobilier_mat_bureau" in label_positions:
        ex, ey = label_positions["equip_mobilier_inst"]
        mx, my = label_positions["mobilier_mat_bureau"]
        if abs(ey - my) < 20 and abs(ex - mx) < 400:
            print(f"      (DEBUG table3 - 'mobilier_mat_bureau' supprime : doublon de la banniere fusionnee 'equip_mobilier_inst' (meme ligne, {abs(ex - mx):.0f}px d'ecart))")
            del label_positions["mobilier_mat_bureau"]
    # --- FIN AJOUT ---

    if not label_positions:
        print(f"      (DEBUG table3 - AUCUN libelle trouve (terrains/constructions/installations/mobilier))")
        return {}

    # AJOUT : diagnostic des quasi-ratés -- un mot OCR qui contient un
    # mot-cle en sous-chaine (pas seulement en prefixe strict) mais qui n'a
    # matche aucun champ. Aide a reperer rapidement des cas comme CDG
    # ("construct" jamais vu du tout) sans devoir republier tout le log.
    all_keywords = {kw for kws in FIELD_KEYWORDS.values() for kw in kws}
    for i, wd in enumerate(clean_words):
        if i in label_word_ids:
            continue
        for kw in all_keywords:
            if len(kw) >= 5 and kw in wd["norm"] and not wd["norm"].startswith(kw):
                print(f"      (DEBUG table3 - quasi-rate: mot OCR {wd['text']!r} contient le mot-cle {kw!r} en sous-chaine, pas en prefixe -> non matche)")

    # --- AJOUT (inference geometrique, cas grille standard 4-champs) ---
    # Constat sur TOUTES les entreprises testees (avant et apres ce fix) :
    # le libelle "Constructions" n'est quasiment jamais lu par l'OCR (raté
    # systematique sur ce mot precis, cause non identifiee -- pas un bug de
    # logique). Le tableau est documente comme une grille 2x2 FIXE : si les
    # 2 libelles de la ligne du bas standard (installations_tech,
    # mobilier_mat_bureau) sont trouves mais un seul des 2 de la ligne du
    # haut (terrains, constructions), on deduit la position du manquant par
    # symetrie de grille -- meme decalage horizontal (dx) que la ligne du
    # bas, meme y que le libelle trouve de la ligne du haut. Purement
    # geometrique (aucune valeur d'entreprise codee en dur) ; ne s'applique
    # qu'au motif standard 4-champs, jamais aux variantes bancaires
    # fusionnees (terrain_construction, equip_mobilier_inst...) dont la
    # grille est differente et qu'on ne veut pas perturber.
    STANDARD_TOP_ROW = ("terrains", "constructions")
    STANDARD_BOTTOM_ROW = ("installations_tech", "mobilier_mat_bureau")
    top_found = set(STANDARD_TOP_ROW) & set(label_positions)
    if len(top_found) == 1 and set(STANDARD_BOTTOM_ROW) <= set(label_positions):
        found_top = top_found.pop()
        missing_top = next(f for f in STANDARD_TOP_ROW if f != found_top)
        bl_x, _ = label_positions["installations_tech"]
        br_x, _ = label_positions["mobilier_mat_bureau"]
        dx = br_x - bl_x
        tx, ty = label_positions[found_top]
        inferred_x = tx + dx if found_top == "terrains" else tx - dx
        label_positions[missing_top] = (inferred_x, ty)
        print(f"      (DEBUG table3 - libelle '{missing_top}' INFERE par geometrie de grille, position ({inferred_x:.0f}, {ty:.0f}))")
    # --- FIN AJOUT ---

    print(f"      (DEBUG table3 - libelles trouves: {list(label_positions.keys())})")

    # 2) tokens numeriques restants
    number_words = []
    for i, wd in enumerate(clean_words):
        if i in label_word_ids:
            continue
        t = wd["text"]
        if t in ("-", "—", "–") or re.fullmatch(r"-?[\d.,]+", t) and re.search(r"\d", t):
            cx = wd["left"] + wd["width"] / 2
            cy = wd["top"] + wd["height"] / 2
            number_words.append({"text": t, "cx": cx, "cy": cy, "left": wd["left"]})

    # 3) assignation : le libelle le plus proche EN DESSOUS (jamais au-dessus)
    print(f"      (DEBUG table3 - {len(number_words)} tokens numeriques trouves: {[n['text'] for n in number_words]})")
    for nw in number_words:
        dists = {f: round(nw["cy"] - ly, 1) for f, (lx, ly) in label_positions.items()}
        print(f"      (DEBUG table3 - '{nw['text']}' cy={nw['cy']:.0f} -> dy par libelle: {dists})")

    # FIX : assignation 1-POUR-1 (au lieu de chaque nombre choisissant son
    # libelle independamment, ce qui permettait a 2 valeurs differentes de
    # "voler" le meme libelle si l'autre n'etait pas detecte -- provoquant
    # le collage "2.576"+"6.153" -> "2.5766153"). On construit TOUTES les
    # paires (nombre, libelle) valides, triees par score croissant, et on
    # assigne glouton en interdisant la reutilisation d'un nombre OU d'un
    # libelle deja pris. Un nombre sans libelle disponible reste ignore --
    # mieux vaut une case vide qu'une valeur fusionnee a tort.
    candidates = []
    for ni, nw in enumerate(number_words):
        for field, (lx, ly) in label_positions.items():
            dy = nw["cy"] - ly
            if dy < -5 or dy > MAX_VALUE_DISTANCE_Y:
                continue
            dx = abs(nw["cx"] - lx)
            score = dy + dx * 0.3
            candidates.append((score, ni, field))
    candidates.sort(key=lambda c: c[0])

    assigned = {field: [] for field in label_positions}
    used_numbers, used_fields = set(), set()
    for score, ni, field in candidates:
        if ni in used_numbers or field in used_fields:
            continue
        assigned[field].append(number_words[ni])
        used_numbers.add(ni)
        used_fields.add(field)

    result = {}
    scores_used = []
    for field, tokens in assigned.items():
        if not tokens:
            continue
        tokens.sort(key=lambda t: t["left"])
        raw = "".join(t["text"] for t in tokens)
        val = _clean_number(raw)
        if val is not None:
            # AJOUT : evite l'affichage "2576.0" trompeur pour un nombre
            # entier -- purement cosmetique, ne change pas la valeur.
            result[field] = int(val) if val == int(val) else val

    # AJOUT (diagnostic pour la selection de passe en amont, run_all_table3.py) :
    # score moyen des assignations retenues. Un score bas = les nombres
    # colles aux libelles sont geometriquement proches (confiance haute) ;
    # un score haut = assignations lointaines, souvent du bruit d'un panneau
    # voisin capture par une boite trop large (voir cas HAO).
    used_scores = [
        score for score, ni, field in candidates
        if field in used_fields and ni in used_numbers and assigned.get(field) and assigned[field][0]["text"] == number_words[ni]["text"]
    ]
    if used_scores:
        result["_diag_avg_score"] = round(sum(used_scores) / len(used_scores), 1)

    return result