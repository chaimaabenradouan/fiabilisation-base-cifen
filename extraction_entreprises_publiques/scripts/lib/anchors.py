"""
anchors.py -- version corrigee
================================================================================
FIX 1 (confirme visuellement sur des captures d'ecran ADM/CDG/OFPPT) : le
bandeau-titre de la section Tableau 1 n'utilise PAS le meme texte partout --
"Informations de base" (ADM) vs "Informations Generales" (CDG, OFPPT). Le
mot-cle "base" est donc absent sur plusieurs pages, ce qui peut degrader la
detection de l'ancre et faire demarrer la zone de recherche trop haut,
capturant alors le bandeau-titre de l'entreprise (juste au-dessus) au lieu
de la case SIGLE -- explique tres probablement le bug "sigle capte le
bandeau-titre" observe precedemment.

Fix : le mot "informations" seul suffit (present dans les deux variantes,
n'apparait nulle part ailleurs sur la page) -- plus besoin du 2e mot-cle
fragile ("base"/"generales").

FIX 2 (analyse logique, PAS ENCORE TESTEE SUR UN VRAI RUN -- a verifier toi-
meme avant de committer) : la formule generique min_hits = max(1, len-1)
appliquee a TOUTES les ancres cree une ambiguite pour les listes courtes.
Exemple concret : indicateurs_activite = ["indicateurs", "activite"] (2 mots)
donnait min_hits=1, donc UN SEUL mot suffisait -- y compris juste
"indicateurs". Or "indicateurs" est aussi le 1er mot-cle de
indicateurs_financiers = ["indicateurs", "economiques", "financiers"]. Une
ligne qui est en realite le bandeau "Indicateurs economiques et financiers"
(ou seul "economiques"/"financiers" a rate l'OCR dans une passe) pouvait donc
satisfaire A LA FOIS le seuil de indicateurs_financiers (2/3) ET celui de
indicateurs_activite (1/2 via le seul mot "indicateurs") -- les deux ancres
se retrouvant alors sur la meme ligne, silencieusement.

Fix : pour une liste courte (<=2 mots-cles), on exige TOUS les mots (pas de
tolerance) ; a partir de 3 mots-cles, on tolere toujours 1 mot manquant
(comportement d'origine inchange pour indicateurs_financiers).

FIX 2bis (regression du FIX 2 ci-dessus, detectee sur un vrai run par
l'utilisateur) : la regle par LONGUEUR DE LISTE durcissait aussi
immo_corporelles (2 mots-cles), sans rapport avec l'ambiguite visee. Sur les
19 entreprises testees, l'ancre immo_corporelles ne se declenchait alors plus
JAMAIS des que l'OCR ratait le mot "corporelles" (frequent) -- repli
systematique sur la fraction fixe, deguisant un bug d'ancrage en fausse
"constante qui marche". Corrige : le durcissement ne s'applique plus qu'a
l'ancre reellement ambigue (indicateurs_activite), toutes les autres,
immo_corporelles incluse, gardent le seuil tolerant d'origine.
"""

from extraction_entreprises_publiques.scripts.lib.ocr_utils import ocr_words, normalize, cluster_lines, line_text

SECTION_ANCHORS = [
    # FIX 1 : un seul mot-cle robuste au lieu de ["informations", "base"]
    # qui ratait "Informations Generales" (CDG, OFPPT...)
    ("informations_de_base", ["informations"]),
    ("indicateurs_financiers", ["indicateurs", "economiques", "financiers"]),
    ("gouvernance", ["gouvernance"]),
    ("indicateurs_activite", ["indicateurs", "activite"]),
    ("immo_corporelles", ["immo", "corporelles"]),
]

UPSCALES = [1.8, 1.4, 2.2]


def _find_in_pass(lines, name, keywords):
    # FIX 2bis (corrige une regression du FIX 2 precedent) : la regle
    # generique "<=2 mots-cles -> tous requis" durcissait AUSSI
    # immo_corporelles (2 mots-cles : "immo","corporelles"), qui n'a pourtant
    # rien a voir avec l'ambiguite indicateurs_activite/indicateurs_financiers
    # visee a l'origine. Resultat observe : l'ancre immo_corporelles ne se
    # declenche plus jamais des que l'OCR rate un seul des deux mots (frequent
    # sur "corporelles", mot plus long et plus fragile a l'OCR) -> repli
    # systematique sur la fraction fixe pour les 19 entreprises.
    # Fix cible : on ne durcit QUE l'ancre concernee par l'ambiguite reelle
    # (indicateurs_activite, qui partage le mot "indicateurs" avec
    # indicateurs_financiers). Toutes les autres ancres, y compris
    # immo_corporelles, gardent le seuil tolerant d'origine (1 mot manquant
    # accepte, quelle que soit la longueur de la liste).
    if name == "indicateurs_activite":
        min_hits = len(keywords)
    else:
        min_hits = max(1, len(keywords) - 1)
    best_line, best_hits = None, 0
    for line in lines:
        norm = normalize(line_text(line))
        hits = sum(1 for kw in keywords if kw in norm)
        if hits > best_hits:
            best_line, best_hits = line, hits
    if best_line is not None and best_hits >= min_hits:
        return best_line["cy"]
    return None


def find_section_anchors(img, x_range=(0, 0.72)):
    w, h = img.size
    box = (int(x_range[0] * w), 0, int(x_range[1] * w), h)

    anchors = {}
    remaining = list(SECTION_ANCHORS)

    for upscale in UPSCALES:
        if not remaining:
            break
        words = ocr_words(img, box, upscale=upscale, psm=11)
        lines = cluster_lines(words, y_tolerance=15)

        still_missing = []
        for name, keywords in remaining:
            cy = _find_in_pass(lines, name, keywords)
            if cy is not None:
                anchors[name] = cy
            else:
                still_missing.append((name, keywords))
        remaining = still_missing

    return anchors