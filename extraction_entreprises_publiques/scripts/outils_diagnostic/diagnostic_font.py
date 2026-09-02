"""
Script de diagnostic - à exécuter LOCALEMENT sur ta machine.
But : comprendre pourquoi le texte extrait ne correspond pas au texte affiché,
et déterminer si un mapping cipher (police custom) est récupérable automatiquement.

Usage:
    python diagnostic_font.py chemin/vers/exemple.pdf

Ne nécessite aucun envoi de fichier à qui que ce soit.
Dépendance: pip install pymupdf
"""

import sys
import fitz  # pymupdf
import json


def diagnostic(pdf_path: str):
    doc = fitz.open(pdf_path)
    print(f"=== Diagnostic pour: {pdf_path} ===")
    print(f"Nombre de pages: {len(doc)}\n")

    for page_num, page in enumerate(doc):
        print(f"--- Page {page_num + 1} ---")

        # 1) Texte brut tel qu'extrait par pymupdf
        raw_text = page.get_text("text")
        print(f"[Texte brut - 300 premiers caractères]:\n{raw_text[:300]}\n")

        # 2) Polices utilisées sur la page
        fonts = page.get_fonts(full=True)
        print(f"[Polices trouvées: {len(fonts)}]")
        for f in fonts:
            xref, ext, ftype, basefont, name, encoding = f[0], f[1], f[2], f[3], f[4], f[5]
            print(f"  xref={xref} type={ftype} basefont={basefont} name={name} encoding={encoding}")

            # Tente d'extraire la table ToUnicode (cmap) si dispo
            try:
                font_dict = doc.xref_object(xref, compressed=False)
                has_tounicode = "ToUnicode" in font_dict
                print(f"    -> Contient ToUnicode: {has_tounicode}")
            except Exception as e:
                print(f"    -> Erreur lecture xref: {e}")

        # 3) Test critique: dict des caractères avec leur code Unicode réel utilisé
        # Ceci nous dit EXACTEMENT quel code Unicode pymupdf assigne à chaque glyphe affiché
        chars_seen = {}
        text_dict = page.get_text("rawdict")
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font_name = span.get("font", "?")
                    for ch in span.get("chars", []):
                        c = ch.get("c", "")
                        code = ord(c) if c else None
                        key = f"{font_name}"
                        chars_seen.setdefault(key, set()).add((c, code))

        print("\n[Echantillon caractères par police - (caractère_extrait, code_unicode)]:")
        for font_name, chars in chars_seen.items():
            sample = sorted(chars, key=lambda x: (x[1] is None, x[1]))[:20]
            print(f"  Police '{font_name}': {sample}")

        print("\n" + "=" * 60 + "\n")

        # On ne traite que la 1ère page pour le diagnostic (change si besoin)
        break

    doc.close()
    print("Diagnostic terminé. Copie-colle ce rapport si tu veux mon analyse — pas besoin d'envoyer le PDF.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python diagnostic_font.py chemin/vers/exemple.pdf")
        sys.exit(1)
    diagnostic(sys.argv[1])