import os
import re
import time
import argparse
from urllib.parse import urljoin

import pandas as pd

# On réutilise ton module existant
from scrape_frenchcleantech import (
    BASE,
    get_soup,
    extract_cards,
    clean_text,
    normalize_company_name,
    normalize_company_name_v2,
)

COMPANIES_URL = urljoin(BASE, "companies.html")


def list_categories() -> list[tuple[str, str]]:
    """
    Retourne une liste de (slug, label) à partir de la page companies.html.
    Robustesse: on extrait tous les href contenant '/categories/<slug>.html' quel que soit le chemin.
    """
    soup = get_soup(COMPANIES_URL)

    found: dict[str, str] = {}
    pattern = re.compile(r"/categories/([a-z0-9\-]+)\.html", re.I)

    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = pattern.search(href)
        if not m:
            continue

        slug = m.group(1).lower().strip()
        label = a.get_text(" ", strip=True) or slug

        label = re.sub(r"\s+", " ", label).strip()
        if not label or label.upper() in {"CATEGORY", "CATEGORIES"}:
            label = slug

        if slug not in found or found[slug] == slug:
            found[slug] = label

    # fallback HTML brut si besoin
    if not found:
        html = soup.decode()
        slugs = sorted(set(m.group(1).lower() for m in pattern.finditer(html)))
        found = {s: s for s in slugs}

    return sorted(found.items(), key=lambda x: x[0])


def scrape_category_autopage(category_slug: str, category_name: str, max_page: int, sleep_s: float) -> pd.DataFrame:
    """
    Scrape une catégorie en auto-pagination:
    - si max_page > 0 : scrape pages 1..max_page (mode debug)
    - si max_page == 0 : scrape jusqu'à ce que:
        - cards == 0, OU
        - la page n'ajoute aucun nouveau detail_url (site renvoie la dernière page en boucle)
    """
    rows = []

    # seen sur l’ensemble de la catégorie
    seen_detail_urls = set()

    page = 1
    while True:
        if max_page and page > max_page:
            break

        url = (
            f"{BASE}companies/categories/{category_slug}.html"
            if page == 1
            else f"{BASE}companies/categories/{category_slug}.html?page={page}"
        )
        print(f"Scraping page {page:02d} -> {url}")

        soup = get_soup(url)
        cards = extract_cards(soup)
        print(f"  Cards trouvées: {len(cards)}")

        # arrêt si page vide (rare sur ce site)
        if not cards:
            break

        before = len(seen_detail_urls)

        for block, readmore_a in cards:
            name_tag = block.find(["h1", "h2", "h3"])
            startup_name = clean_text(name_tag.get_text()) if name_tag else ""

            tagline = ""
            if name_tag:
                sib = name_tag.find_next_sibling()
                for _ in range(3):
                    if sib is None:
                        break
                    t = clean_text(sib.get_text(" ", strip=True))
                    if t and "read more" not in t.lower():
                        tagline = t
                        break
                    sib = sib.find_next_sibling()

            detail_url = urljoin(BASE, readmore_a.get("href", ""))

            # Dédup robuste: si aucune nouvelle URL n'apparaît sur une page,
            # c'est que le site renvoie la même page (ex: dernière page) => STOP.
            if detail_url in seen_detail_urls:
                continue

            seen_detail_urls.add(detail_url)
            rows.append({
                "startup_name": startup_name,
                "tagline": tagline,
                "detail_url": detail_url,
                "category": category_name,
                "list_page": page
            })

        after = len(seen_detail_urls)
        new_added = after - before

        # STOP condition anti-boucle: page sans nouveauté
        if new_added == 0:
            print(f"  STOP: aucune nouvelle entreprise détectée à page={page} (probable répétition dernière page).")
            break

        time.sleep(sleep_s)
        page += 1

    df = pd.DataFrame(rows).drop_duplicates(subset=["startup_name", "detail_url"]).reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser(description="Scrape ALL FrenchCleantech categories (auto-pagination robuste).")
    parser.add_argument(
        "--max-page",
        type=int,
        default=0,
        help="Max pages per category. 0 = autopagination (RECOMMANDÉ)."
    )
    parser.add_argument("--sleep", type=float, default=0.6, help="Delay between pages in seconds.")
    parser.add_argument("--outdir", default=os.path.join("data", "raw"), help="Output directory (default: data/raw).")
    parser.add_argument("--limit-categories", type=int, default=0, help="If >0, scrape only first N categories (debug).")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    print("Fetching categories from:", COMPANIES_URL)
    categories = list_categories()
    print("Nb catégories détectées:", len(categories))
    if categories:
        print("Exemples:", categories[:10])

    if not categories:
        raise RuntimeError("Impossible de détecter les catégories sur companies.html.")

    if args.limit_categories and args.limit_categories > 0:
        categories = categories[:args.limit_categories]
        print("Mode debug: catégories limitées à", len(categories))

    all_rows = []
    for i, (slug, label) in enumerate(categories, start=1):
        print(f"\n[{i}/{len(categories)}] Category: {label} (slug={slug})")
        df_cat = scrape_category_autopage(slug, label, max_page=args.max_page, sleep_s=args.sleep)
        all_rows.append(df_cat)
        time.sleep(args.sleep)

    df_all = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if df_all.empty:
        raise RuntimeError("Aucune donnée scrapée. Vérifie la structure du site / la connexion.")

    # Normalisations
    df_all["name_clean"] = df_all["startup_name"].apply(normalize_company_name)
    df_all["name_clean_v2"] = df_all["startup_name"].apply(normalize_company_name_v2)

    # RAW global
    path_raw_all = os.path.join(args.outdir, "frenchcleantech_all.csv")
    df_all.drop_duplicates(subset=["startup_name", "detail_url", "category"]).to_csv(
        path_raw_all, index=False, encoding="utf-8-sig"
    )

    # COMPANIES global (entreprises uniques)
    df_companies_all = (
        df_all.sort_values(["category", "list_page"], ascending=True)
             .drop_duplicates(subset=["name_clean_v2"])
             .reset_index(drop=True)
    ).copy()

    path_companies_all = os.path.join(args.outdir, "frenchcleantech_all_companies.csv")
    df_companies_all.to_csv(path_companies_all, index=False, encoding="utf-8-sig")

    print("\nSaved RAW:", path_raw_all, "| rows:", len(df_all))
    print("Saved COMPANIES:", path_companies_all, "| unique companies:", len(df_companies_all))
    print("Tip: mode prod = --max-page 0 (auto)")


if __name__ == "__main__":
    main()