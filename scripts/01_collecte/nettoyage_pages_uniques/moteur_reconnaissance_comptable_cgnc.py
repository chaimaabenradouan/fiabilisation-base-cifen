#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
localization_engine_v2.py
=========================================================================
CORRECTIF par rapport à la v1 :

    La v1 utilisait un scoring FLOU (difflib) pour choisir la bonne page
    (robuste à la police corrompue de type "chiEEre" au lieu de
    "chiffre"), mais localisait ensuite la bbox du tableau avec
    page.search_for("BILAN ACTIF") — une recherche EXACTE. Sur les
    documents à police corrompue (ceux qui ont justement motivé le
    fuzzy matching), search_for() ne trouve rien, et le code retombait
    sur un placeholder [40, 60, 555, 750] = quasi toute la page. Résultat :
    MinerU en aval recevait une bbox qui n'isolait rien du tout.

    v2 : au lieu de chercher un TITRE, on détecte la STRUCTURE réelle des
    tableaux sur la page (page.find_tables(), basé sur les lignes/grilles
    du PDF, insensible à la police du texte). Chaque tableau détecté est
    ensuite scoré (fuzzy) selon le texte qu'il contient, pour savoir s'il
    s'agit du Bilan Actif, Bilan Passif, ou CPC. La bbox retenue est donc
    TOUJOURS la bbox réelle d'un tableau existant, jamais un placeholder.

    Les dictionnaires de mots-clés pondérés (nomenclature CGNC complète)
    sont repris de mineru_extract_tables.py pour une couverture maximale.

Usage :
    python localization_engine_v2.py --pdf "Rapports/MANAGEM/2018.pdf"
    python localization_engine_v2.py --pdf "Rapports/MANAGEM/2018.pdf" --variant consolide
    python localization_engine_v2.py --pdf "Rapports/MANAGEM/2018.pdf" --render-crops

Sortie :
    <pdf_stem>_localization.json   (à côté du PDF, même schéma que la v1
    + champs additionnels : matched_keywords, methode_bbox)
    <pdf_stem>_localization_crops/*.png   (si --render-crops)
=========================================================================
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

# =========================================================================
# 1. RÉFÉRENTIEL - nomenclature CGNC complète et pondérée
#    (repris de mineru_extract_tables.py pour cohérence entre les 2 scripts)
# =========================================================================

KEYWORDS_IDENTIFICATION: dict[str, int] = {
    "numero de registre du commerce et code du centre de registre du commerce": 22,
    "code du centre de registre du commerce": 16,
    "numero de registre du commerce": 18,
    "registre du commerce": 16,
    "nom de l entreprise": 16,
    "identifiant commun de l entreprise": 22,
    "ice": 14,
    "raison sociale": 20,
    "denomination sociale": 18,
    "denomination": 9,
    "siege social": 18,
    "adresse du siege": 10,
    "forme juridique": 12,
    "capital social": 8,
    "activite principale": 10,
    "secteur d activite": 10,
    "objet social": 10,
    "date de constitution": 12,
    "exercice social": 6,
    "numero d identification fiscale": 14,
    "identifiant fiscal": 12,
    "patente": 10,
    "cnss": 8,
}

KEYWORDS_BILAN_ACTIF: dict[str, int] = {
    "actif immobilise": 18, "immobilisations en non valeur": 16,
    "immobilisations incorporelles": 15, "immobilisations corporelles": 15,
    "immobilisations financieres": 15, "actif circulant": 16,
    "creances de l actif circulant": 16, "tresorerie actif": 22, "total actif": 26,
    "stocks": 8, "immobilisations": 6, "actif": 4,
    "frais preliminaires": 6, "charges a repartir sur plusieurs exercices": 6,
    "primes de remboursement des obligations": 6,
    "immobilisation en recherche et developpement": 6,
    "brevets marques droits et valeurs similaires": 6, "fonds commercial": 6,
    "autres immobilisations incorporelles": 5, "terrains": 5, "constructions": 5,
    "installations techniques materiel et outillage": 7, "materiel de transport": 5,
    "mobilier materiel de bureau et amenagements divers": 7,
    "autres immobilisations corporelles": 5, "immobilisations corporelles en cours": 7,
    "prets immobilises": 5, "autres creances financieres": 5,
    "titres de participation": 6, "autres titres immobilises": 5,
    "ecarts de conversion actif": 9, "diminution des creances immobilisees": 5,
    "augmentation des dettes de financement": 5, "marchandises": 5,
    "matieres et fournitures consommables": 6, "produits en cours": 5,
    "produits intermediaires et produits residuels": 6, "produits finis": 5,
    "fournisseurs debiteurs avances et acomptes": 6,
    "clients et comptes rattaches": 9, "comptes d associes": 4,
    "autres debiteurs": 5, "comptes de regularis actif": 6,
    "titres et valeurs de placement": 6,
    "ecarts de conversion actif elements circulants": 6,
    "cheques et valeurs a encaisser": 6, "banques t g et c c p": 6,
    "caisses regies d avances et accreditifs": 6, "personnel": 3, "etat": 3,
}

KEYWORDS_BILAN_PASSIF: dict[str, int] = {
    "capitaux propres": 20, "total des capitaux propres": 22,
    "capitaux propres assimiles": 12, "dettes de financement": 16,
    "provisions durables pour risques et charges": 12, "passif circulant": 16,
    "dettes du passif circulant": 18, "tresorerie passif": 22, "total passif": 26,
    "passif": 4, "capital social ou personnel": 10,
    "primes d emission de fusion et d apport": 6, "ecarts de reevaluation": 5,
    "reserve legale": 6, "autres reserves": 5, "report a nouveau": 6,
    "resultats nets en instance d affectation": 6, "resultat net de l exercice": 10,
    "subventions d investissement": 6, "provisions reglementees": 5,
    "emprunts obligataires": 6, "autres dettes de financement": 5,
    "provisions pour risques": 6, "provisions pour charges": 6,
    "provisions pour risques et charges": 10, "ecarts de conversion passif": 9,
    "augmentation des creances immobilisees": 5, "diminution des dettes de financement": 5,
    "fournisseurs et comptes rattaches": 9, "clients crediteurs avances et acomptes": 6,
    "organismes sociaux": 6, "autres creanciers": 5,
    "comptes de regularisation passif": 6, "autres provisions pour risques et charges": 6,
    "ecarts de conversion passif elements circulants": 6, "credits d escompte": 6,
    "credits de tresorerie": 6, "banques soldes crediteurs": 6,
    "personnel": 3, "etat": 3,
}

KEYWORDS_CPC: dict[str, int] = {
    "compte de produits et charges": 26, "chiffre d affaires": 20,
    "chiffres d affaires": 12, "produits d exploitation": 18,
    "charges d exploitation": 18, "resultat d exploitation": 18,
    "produits financiers": 10, "charges financieres": 10, "resultat financier": 14,
    "resultat courant": 14, "produits non courants": 10, "charges non courantes": 10,
    "resultat non courant": 12, "resultat avant impots": 15,
    "impots sur les resultats": 10, "resultat net": 8,
    "ventes de marchandises": 6, "ventes de biens et services produits": 6,
    "variation des stocks de produits": 6,
    "immobilisations produites par l entreprise pour elle meme": 6,
    "subventions d exploitation": 5, "autres produits d exploitation": 5,
    "reprises d exploitation transferts de charges": 6,
    "achats revendus de marchandises": 6,
    "achats consommes de matieres et fournitures": 6, "autres charges externes": 5,
    "impots et taxes": 5, "charges de personnel": 6,
    "autres charges d exploitation": 5, "dotations d exploitation": 6,
    "produits des titres de participation et autres titres immobilises": 5,
    "gains de change": 5, "interets et autres produits financiers": 5,
    "reprises financieres transferts de charges": 5, "charges d interets": 5,
    "pertes de change": 5, "autres charges financieres": 5, "dotations financieres": 5,
    "produits des cessions d immobilisations": 5, "subventions d equilibre": 5,
    "reprises sur subventions d investissement": 5, "autres produits non courants": 5,
    "reprises non courantes transferts de charges": 5,
    "valeurs nettes d amortissements des immobilisations cedees": 5,
    "subventions accordees": 4, "autres charges non courantes": 5,
    "dotations non courantes aux amortissements et aux provisions": 5,
}

CATEGORY_KEYWORDS = {
    "identification": KEYWORDS_IDENTIFICATION,
    "bilan_actif": KEYWORDS_BILAN_ACTIF,
    "bilan_passif": KEYWORDS_BILAN_PASSIF,
    "cpc": KEYWORDS_CPC,
}

SOCIAL_MARKERS = ["comptes sociaux", "hors taxes", "compte de produits et charges", "cgnc"]
CONSOLIDATED_MARKERS = ["comptes consolides", "consolide", "ifrs", "normes internationales",
                         "international financial reporting"]

FUZZY_THRESHOLD = 0.78
MIN_SCORE_PAGE = 24        # score minimum pour qu'une page soit candidate
MIN_SCORE_TABLE = 15       # score minimum pour qu'un tableau détecté soit assigné à une catégorie

# Mots très courants utilisés pour sonder si la police du document est
# corrompue. S'ils apparaissent tels quels quelque part dans les premières
# pages, le matching exact suffit -> on désactive le fallback flou (coûteux)
# pour tout le reste du document. Sinon, on l'active (document suspect).
CORRUPTION_PROBE_TERMS = ["bilan", "actif", "passif", "total", "resultat"]
CORRUPTION_PROBE_MIN_HITS = 3


# =========================================================================
# 2. NORMALISATION ET MATCHING FLOU
# =========================================================================

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def fuzzy_contains(keyword_norm: str, text_norm: str, threshold: float = FUZZY_THRESHOLD,
                    use_fuzzy: bool = True) -> bool:
    if keyword_norm in text_norm:
        return True
    if not use_fuzzy:
        return False
    klen = len(keyword_norm)
    if klen == 0:
        return False
    step = max(1, klen // 4)
    # Optimisation : seq2 (le mot-clé, fixe) est réglé une seule fois hors boucle.
    # quick_ratio() est un majorant rapide (O(n)) qui élimine la plupart des
    # fenêtres AVANT le calcul coûteux de ratio() (recherche des blocs communs).
    sm = difflib.SequenceMatcher()
    sm.set_seq2(keyword_norm)
    for i in range(0, max(1, len(text_norm) - klen + 1), step):
        window = text_norm[i:i + klen]
        sm.set_seq1(window)
        if sm.quick_ratio() < threshold:
            continue
        if sm.ratio() >= threshold:
            return True
    return False


def score_against_category(text: str, keywords: dict[str, int], use_fuzzy: bool = True) -> tuple[int, list[str]]:
    norm = normalize(text)
    score = 0
    matched = []
    for kw, weight in keywords.items():
        if fuzzy_contains(kw, norm, use_fuzzy=use_fuzzy):
            score += weight
            matched.append(kw)
    return min(score, 100), matched


# =========================================================================
# 3. STRUCTURES
# =========================================================================

@dataclass
class LocalizedElement:
    type: str
    pages: list[int]
    bbox: list[float]
    confidence: float
    score: float
    reasoning: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    variant: str = "social"
    methode_bbox: str = "table_detectee"   # "table_detectee" | "page_entiere_fallback"


# =========================================================================
# 4. MOTEUR
# =========================================================================

class FinancialStatementLocalizationEngineV2:
    def __init__(self, pdf_path: Path, target_variant: str = "social", output_dir: Optional[Path] = None):
        self.pdf_path = Path(pdf_path)
        self.target_variant = target_variant
        self.output_dir = Path(output_dir) if output_dir else self.pdf_path.parent
        self.doc = fitz.open(pdf_path)
        self.page_texts: dict[int, str] = {}
        self.page_variants: dict[int, str] = {}

        self._extract_page_texts()               # 1) juste le texte brut, aucun matching
        self.use_fuzzy = self._detect_font_corruption()   # 2) sonde rapide, exact-only
        if self.use_fuzzy:
            print("   ⚠️  Police potentiellement corrompue détectée -> matching flou activé (plus lent)")
        self._compute_page_variants()             # 3) variantes, avec le bon flag fuzzy connu

    def _extract_page_texts(self):
        for page_num in range(len(self.doc)):
            self.page_texts[page_num] = self.doc[page_num].get_text("text")

    def _detect_font_corruption(self) -> bool:
        """Sonde rapide et TOUJOURS exacte (jamais floue, pour rester instantanée) :
        si les mots les plus courants d'un état financier n'apparaissent nulle part
        tels quels dans un échantillon de pages, la police est probablement
        corrompue -> on active le matching flou pour tout le reste du document.
        Sinon (cas normal), on le désactive : le matching exact suffit et reste rapide."""
        sample = list(self.page_texts.values())[:min(15, len(self.page_texts))]
        combined_norm = normalize(" ".join(sample))
        hits = sum(1 for term in CORRUPTION_PROBE_TERMS if term in combined_norm)
        return hits < CORRUPTION_PROBE_MIN_HITS

    def _compute_page_variants(self):
        for page_num, text in self.page_texts.items():
            self.page_variants[page_num] = self._detect_variant(text)

    def _detect_variant(self, text: str) -> str:
        norm = normalize(text)
        social_hits = sum(1 for m in SOCIAL_MARKERS if fuzzy_contains(m, norm, use_fuzzy=self.use_fuzzy))
        consolidated_hits = sum(1 for m in CONSOLIDATED_MARKERS if fuzzy_contains(m, norm, use_fuzzy=self.use_fuzzy))
        if consolidated_hits > social_hits:
            return "consolide"
        if social_hits > 0:
            return "social"
        return "indetermine"

    def _page_coherence_bonus(self, page: int) -> tuple[int, list[str]]:
        text = self.page_texts[page]
        hits = sum(1 for t in ("bilan_actif", "bilan_passif", "cpc")
                   if score_against_category(text, CATEGORY_KEYWORDS[t], use_fuzzy=self.use_fuzzy)[0] > 0)
        return (40, ["page_coherente_3_etats"]) if hits == 3 else (0, [])

    def _choose_candidate_pages(self) -> dict[str, tuple[int, int, list[str], str]]:
        """Pour chaque catégorie (bilan_actif/passif/cpc), choisit la meilleure page
        (score + bonus de cohérence), en priorisant la variante cible."""
        chosen = {}
        for cat in ("bilan_actif", "bilan_passif", "cpc"):
            candidates = []
            for p, text in self.page_texts.items():
                page_variant = self.page_variants[p]
                if page_variant != self.target_variant and page_variant != "indetermine":
                    continue
                score, matched = score_against_category(text, CATEGORY_KEYWORDS[cat], use_fuzzy=self.use_fuzzy)
                bonus, bonus_reasoning = self._page_coherence_bonus(p)
                candidates.append((score + bonus, p, matched + bonus_reasoning, page_variant))

            if not candidates or max(c[0] for c in candidates) < MIN_SCORE_PAGE:
                candidates = []
                for p, text in self.page_texts.items():
                    score, matched = score_against_category(text, CATEGORY_KEYWORDS[cat], use_fuzzy=self.use_fuzzy)
                    bonus, bonus_reasoning = self._page_coherence_bonus(p)
                    candidates.append((score + bonus, p, matched + bonus_reasoning, self.page_variants[p]))

            best = max(candidates, key=lambda c: c[0])
            if best[0] >= MIN_SCORE_PAGE:
                chosen[cat] = best
        return chosen

    def _find_identification(self) -> Optional[LocalizedElement]:
        for p, text in self.page_texts.items():
            score, matched = score_against_category(text, KEYWORDS_IDENTIFICATION, use_fuzzy=self.use_fuzzy)
            bonus = 25 if p == 0 else 0
            total = score + bonus
            if total >= 60:
                return LocalizedElement(
                    type="identification", pages=[p], bbox=[0, 0, self.doc[p].rect.width, 400],
                    confidence=min(total / 100, 0.95), score=total,
                    reasoning=[f"page_{p}", "identification_zone_haut_page"],
                    matched_keywords=matched, variant=self.page_variants[p],
                    methode_bbox="zone_haut_page",  # l'identification est un bloc de texte, pas un tableau
                )
        return None

    def _refine_bbox_to_matching_rows(self, table, cat: str) -> Optional[fitz.Rect]:
        """Quand find_tables() fusionne plusieurs états financiers en UN SEUL
        tableau détecté (ex: Actif+Passif côte à côte, ou les 3 empilés), le
        bbox du tableau entier est trop large et capture plusieurs catégories
        à la fois. On descend donc au niveau des LIGNES du tableau : on score
        chaque ligne séparément, on garde la plus longue série CONTIGUË de
        lignes qui matchent la catégorie visée, et on recalcule un bbox
        restreint à ces lignes uniquement."""
        try:
            row_texts = table.extract()
        except Exception:
            return None
        if not row_texts or not table.rows:
            return None

        keywords = CATEGORY_KEYWORDS[cat]
        matching_indices = []
        for i, row_cells in enumerate(row_texts):
            row_text = " ".join(c or "" for c in row_cells)
            score, _ = score_against_category(row_text, keywords, use_fuzzy=self.use_fuzzy)
            if score > 0:
                matching_indices.append(i)

        if not matching_indices:
            return None

        # Regroupe en plages contiguës (tolère un petit trou de 2 lignes :
        # sous-titre, ligne de total sans mot-clé, etc.)
        ranges = []
        start = prev = matching_indices[0]
        for idx in matching_indices[1:]:
            if idx - prev > 2:
                ranges.append((start, prev))
                start = idx
            prev = idx
        ranges.append((start, prev))
        row_start, row_end = max(ranges, key=lambda r: r[1] - r[0])

        cell_rects = []
        for i in range(row_start, min(row_end + 1, len(table.rows))):
            for cell in table.rows[i].cells:
                if cell is not None:
                    cell_rects.append(cell)

        if not cell_rects:
            return None

        x0 = min(c[0] for c in cell_rects)
        y0 = min(c[1] for c in cell_rects)
        x1 = max(c[2] for c in cell_rects)
        y1 = max(c[3] for c in cell_rects)
        return fitz.Rect(x0 - 5, y0 - 15, x1 + 5, y1 + 10)

    def _find_table_bbox_for_category(self, page: int, cat: str) -> tuple[Optional[fitz.Rect], list[str], str]:
        """CORRECTIF PRINCIPAL : détecte les tableaux RÉELS de la page (structure,
        insensible à la police), puis score le texte de chaque tableau pour
        trouver celui qui correspond le mieux à la catégorie recherchée."""
        pg = self.doc[page]
        try:
            tables = pg.find_tables()
        except Exception:
            tables = None

        if not tables or len(tables.tables) == 0:
            # Aucun tableau structurel détecté (rare, mais possible sur des
            # tableaux sans bordures nettes) -> fallback explicite et TRACÉ,
            # pas un placeholder silencieux comme dans la v1.
            return None, ["aucun_tableau_detecte_sur_la_page"], "page_entiere_fallback"

        best_score = -1
        best_rect = None
        best_matched = []
        best_table = None
        for table in tables.tables:
            rect = fitz.Rect(table.bbox)
            table_text = pg.get_text("text", clip=rect)
            score, matched = score_against_category(table_text, CATEGORY_KEYWORDS[cat], use_fuzzy=self.use_fuzzy)
            if score > best_score:
                best_score = score
                best_rect = rect
                best_matched = matched
                best_table = table

        if best_score < MIN_SCORE_TABLE:
            # Des tableaux existent sur la page mais aucun ne correspond
            # clairement à la catégorie -> on le signale au lieu de deviner.
            return None, [f"tableaux_detectes_mais_aucun_ne_matche_{cat}_(meilleur_score={best_score})"], "page_entiere_fallback"

        # Le tableau détecté couvre-t-il une grande partie de la page ? Si oui,
        # il fusionne probablement plusieurs états financiers -> on tente un
        # affinage ligne par ligne pour isoler juste la catégorie recherchée.
        page_area = pg.rect.width * pg.rect.height
        table_area = best_rect.width * best_rect.height
        if table_area / page_area > 0.35:
            refined = self._refine_bbox_to_matching_rows(best_table, cat)
            if refined is not None:
                return refined, best_matched + ["bbox_affinee_par_lignes"], "table_detectee_affinee"
            # L'affinage a échoué : on garde le tableau entier, mais on le
            # signale clairement plutôt que de faire comme si de rien n'était.
            return best_rect, best_matched + ["tableau_large_non_affine_a_verifier"], "table_large_non_affinee"

        return best_rect, best_matched, "table_detectee"

    def run(self, render_crops: bool = False) -> dict:
        print(f"🚀 Analyse : {self.pdf_path.name} (variante cible: {self.target_variant})")

        elements: dict[str, LocalizedElement] = {}

        ident = self._find_identification()
        if ident:
            elements["identification"] = ident

        chosen_pages = self._choose_candidate_pages()

        for cat, (score, page, reasoning, variant) in chosen_pages.items():
            rect, matched, methode = self._find_table_bbox_for_category(page, cat)

            if rect is not None:
                bbox = [round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1)]
                confidence = min(score / 160, 0.95)
            else:
                pg = self.doc[page]
                bbox = [20.0, 20.0, round(pg.rect.width - 20, 1), round(pg.rect.height - 20, 1)]
                confidence = min(score / 160, 0.5)  # confiance réduite : c'est un vrai fallback, pas une vraie détection

            elements[cat] = LocalizedElement(
                type=cat, pages=[page], bbox=bbox, confidence=confidence, score=score,
                reasoning=reasoning + matched, matched_keywords=matched,
                variant=variant, methode_bbox=methode,
            )

        result = {
            "document": self.pdf_path.name,
            "processed_at": datetime.now().isoformat(),
            "version": "6.0-tables-reelles",
            "target_variant": self.target_variant,
            "identification": asdict(elements["identification"]) if "identification" in elements else None,
            "financial_statements": [asdict(v) for k, v in elements.items() if k != "identification"],
        }

        output_path = self.output_dir / f"{self.pdf_path.stem}_localization.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"\n✅ localization.json créé -> {output_path}")
        for k, v in elements.items():
            flag = "⚠️ FALLBACK" if v.methode_bbox != "table_detectee" and k != "identification" else "✅"
            print(f"   {flag} {k:15s} -> page {v.pages[0]}  bbox={v.bbox}  "
                  f"confiance={v.confidence:.2f}  méthode={v.methode_bbox}")

        if render_crops:
            self._render_crops(elements)

        return result

    def _render_crops(self, elements: dict[str, LocalizedElement]):
        out_dir = self.output_dir / f"{self.pdf_path.stem}_localization_crops"
        out_dir.mkdir(exist_ok=True)
        for t, el in elements.items():
            page = self.doc[el.pages[0]]
            rect = fitz.Rect(*el.bbox)
            pix = page.get_pixmap(clip=rect, dpi=200)
            out_path = out_dir / f"{t}.png"
            pix.save(out_path)
            print(f"   🖼️  {t} -> {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--variant", choices=["social", "consolide"], default="social")
    parser.add_argument("--output-dir", type=Path, default=None,
                         help="Dossier de sortie (défaut : à côté du PDF)")
    parser.add_argument("--render-crops", action="store_true",
                         help="Sauvegarde un PNG découpé par élément localisé (vérification visuelle)")
    args = parser.parse_args()

    engine = FinancialStatementLocalizationEngineV2(args.pdf, target_variant=args.variant, output_dir=args.output_dir)
    engine.run(render_crops=args.render_crops)