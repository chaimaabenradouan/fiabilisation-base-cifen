"""
generate_emetteurs.py - Version Pagination Robuste (v2 - gère les "...")
=========================================================================

CORRECTION du bug principal : le site casablanca-bourse.com masque les
numéros de page intermédiaires derrière des points de suspension "..."
dès qu'il y a plus de ~4 pages (ex: 1  2  3  4  ...  6). L'ancienne
version cherchait un bouton avec le texte EXACT du numéro suivant
("5"), qui n'existe pas dans le DOM tant qu'on n'a pas cliqué sur "...".
Résultat : la pagination s'arrêtait silencieusement à la page 4, et
toutes les entreprises des pages suivantes (ex: BMCI) étaient perdues
SANS AUCUNE ERREUR visible.

Cette version :
    1. Essaie d'abord le bouton numéroté exact (cas simple, page visible)
    2. Sinon, cherche une flèche "suivant" (»› / aria-label Suivant/Next),
       qui reste presque toujours visible même quand les numéros
       intermédiaires sont cachés
    3. Sinon, clique sur les "..." pour révéler les numéros cachés, puis
       clique sur le numéro suivant
    4. Après CHAQUE clic, vérifie que le contenu du tableau a réellement
       changé (comparaison des noms d'entreprises affichés). Si rien n'a
       changé, on considère qu'on est bloqué et on s'arrête PROPREMENT
       avec un avertissement clair, plutôt que de boucler à l'infini ou
       de dupliquer des données.
    5. Déduplique par URL_Fiche (pas seulement par nom) pour éviter les
       doublons si une page est lue deux fois.
=========================================================================
"""

import csv
import time
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.casablanca-bourse.com"
OUTPUT_CSV = Path("liste_emetteurs.csv")
MAX_PAGES = 30  # garde-fou de sécurité


def normalize_for_folder(name: str) -> str:
    text = re.sub(r'[\\/*?:"<>|]', "", name)
    return re.sub(r'\s+', "_", text.strip())[:120]


def extract_rows(page) -> list[dict]:
    """Extrait les lignes du tableau actuellement affiché."""
    rows_data = []
    rows = page.query_selector_all("table tbody tr, table tr")

    for row in rows:
        try:
            cells = row.query_selector_all("td")
            if len(cells) < 2:
                continue

            nom_cell = cells[0].inner_text().strip()
            if not nom_cell or len(nom_cell) < 3:
                continue

            link = cells[0].query_selector("a")
            href = link.get_attribute("href") if link else None
            full_url = f"{BASE_URL}{href}" if href and href.startswith("/") else (href or "")

            rows_data.append({
                "Nom": nom_cell,
                "URL_Fiche": full_url,
                "Folder_Name": normalize_for_folder(nom_cell),
            })
        except Exception:
            continue

    return rows_data


def get_visible_page_numbers(page) -> list[int]:
    """Retourne tous les numéros de page actuellement visibles dans la
    barre de pagination (utile pour connaître le nombre total réel de
    pages même si des numéros intermédiaires sont cachés derrière '...')."""
    numbers = []
    candidates = page.locator("li.page-item, button, a").all()
    for el in candidates:
        try:
            txt = el.inner_text().strip()
            if txt.isdigit():
                numbers.append(int(txt))
        except Exception:
            continue
    return numbers


def click_next_page(page, current_page_num: int) -> bool:
    """Tente de passer à la page suivante de façon robuste, y compris
    quand le numéro de page est caché derrière des points de suspension.
    Retourne True si un clic a été effectué, False si aucune option
    n'a été trouvée (fin probable de la pagination)."""
    next_num = str(current_page_num + 1)

    # --- 1) Bouton numéroté exact, directement visible ---
    direct_btn = page.locator(f"button:text-is('{next_num}'), a:text-is('{next_num}')").first
    if direct_btn.count() > 0 and direct_btn.is_visible():
        direct_btn.click()
        return True

    # --- 2) Flèche "suivant" (survit généralement aux "...") ---
    next_arrow = page.locator(
        "button[aria-label*='uivant'], a[aria-label*='uivant'], "
        "button[aria-label*='ext'], a[aria-label*='ext'], "
        "button:has-text('»'), a:has-text('»'), "
        "button:has-text('›'), a:has-text('›'), "
        "li.next a, li.next button"
    ).first
    if next_arrow.count() > 0 and next_arrow.is_visible():
        classes = (next_arrow.get_attribute("class") or "")
        disabled_attr = next_arrow.get_attribute("disabled")
        aria_disabled = next_arrow.get_attribute("aria-disabled")
        if disabled_attr is not None or "disabled" in classes or aria_disabled == "true":
            pass  # flèche désactivée -> on tente quand même les points de suspension ci-dessous
        else:
            next_arrow.click()
            return True

    # --- 3) Points de suspension "..." : les cliquer pour révéler les
    #        numéros cachés, puis cliquer sur le numéro suivant ---
    ellipsis = page.locator("button:text-is('...'), a:text-is('...'), span:text-is('...'), li:has-text('...')").first
    if ellipsis.count() > 0 and ellipsis.is_visible():
        ellipsis.click()
        time.sleep(1)
        revealed_btn = page.locator(f"button:text-is('{next_num}'), a:text-is('{next_num}')").first
        if revealed_btn.count() > 0 and revealed_btn.is_visible():
            revealed_btn.click()
            return True

    return False


def scrape_all_issuers():
    emitters_by_url: dict[str, dict] = {}  # dédup par URL_Fiche

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=700)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            print("🔄 Ouverture de la page des émetteurs...")
            page.goto(f"{BASE_URL}/fr/listing-des-emetteurs", wait_until="networkidle", timeout=90000)
            time.sleep(4)

            visible_numbers = get_visible_page_numbers(page)
            if visible_numbers:
                print(f"ℹ️  Numéros de page visibles dès le départ : {sorted(set(visible_numbers))} "
                      f"(le dernier n'est pas forcément le nombre total réel si des '...' existent)")

            page_num = 1
            previous_names_signature = None

            while page_num <= MAX_PAGES:
                print(f"📄 Scraping page {page_num}...")

                rows = extract_rows(page)
                names_signature = tuple(sorted(r["Nom"] for r in rows))

                if previous_names_signature is not None and names_signature == previous_names_signature:
                    print("⚠️  Le contenu de la page n'a pas changé après le clic précédent — "
                          "on considère que la pagination est bloquée ou terminée. Arrêt propre.")
                    break

                added = 0
                for r in rows:
                    key = r["URL_Fiche"] or r["Nom"]
                    if key not in emitters_by_url:
                        emitters_by_url[key] = r
                        added += 1

                print(f"   → {added} nouveaux émetteurs ajoutés sur cette page (Total unique : {len(emitters_by_url)})")
                previous_names_signature = names_signature

                moved = click_next_page(page, page_num)
                if not moved:
                    print("✅ Fin de pagination détectée (aucun bouton suivant trouvé).")
                    break

                time.sleep(3)
                page_num += 1

            if page_num > MAX_PAGES:
                print(f"⚠️  Limite de sécurité MAX_PAGES={MAX_PAGES} atteinte — "
                      f"vérifie s'il reste des pages non lues.")

        except Exception as e:
            print(f"❌ Erreur générale : {e}")
        finally:
            browser.close()

    emitters = list(emitters_by_url.values())

    if emitters:
        OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Nom", "URL_Fiche", "Folder_Name"])
            writer.writeheader()
            writer.writerows(emitters)

        print(f"\n🎉 Succès ! {len(emitters)} émetteurs uniques sauvegardés dans {OUTPUT_CSV.resolve()}")
    else:
        print("⚠️ Aucun émetteur récupéré.")


if __name__ == "__main__":
    scrape_all_issuers()