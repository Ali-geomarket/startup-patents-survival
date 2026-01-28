import os
import re
import time
import unicodedata
from urllib.parse import urljoin
import argparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36"
    )
}

BASE = "https://www.frenchcleantech.com/"

LEGAL_FORMS = {
    "SAS", "SASU", "SARL", "SA", "SNC", "EURL", "GIE",
    "LTD", "LIMITED", "INC", "CORP", "CORPORATION",
    "BV", "GMBH", "SPA", "SRL"
}


def clean_text(x: str) -> str:
    if not x:
        return ""
    return re.sub(r"\s+", " ", str(x)).strip()


def get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def extract_cards(soup: BeautifulSoup):
    """
    Repère les liens 'Read more' puis remonte au bloc contenant un titre (h1/h2/h3).
    Retourne une liste de tuples: (block_html, readmore_link)
    """
    read_more = soup.find_all("a", string=re.compile(r"read more", re.I))
    cards = []
    for a in read_more:
        block = a
        for _ in range(10):
            block = block.parent
            if block is None:
                break
            title = block.find(["h1", "h2", "h3"])
            if title and clean_text(title.get_text()):
                cards.append((block, a))
                break
    return cards


def normalize_company_name(name: str) -> str:
    """Normalisation simple."""
    if not isinstance(name, str):
        return ""
    x = name.upper()
    x = unicodedata.normalize("NFKD", x)
    x = "".join(c for c in x if not unicodedata.combining(c))
    x = re.sub(r"[^A-Z0-9]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    tokens = [t for t in x.split() if t not in LEGAL_FORMS]
    return " ".join(tokens)


def normalize_company_name_v2(name: str) -> str:
    """Normalisation améliorée : recolle certains tokens (S TILE -> STILE)."""
    if not isinstance(name, str):
        return ""
    x = name.upper()
    x = unicodedata.normalize("NFKD", x)
    x = "".join(c for c in x if not unicodedata.combining(c))
    x = re.sub(r"[^A-Z0-9]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()

    tokens = [t for t in x.split() if t not in LEGAL_FORMS]

    merged = []
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens) and len(tokens[i]) == 1 and len(tokens[i + 1]) <= 4:
            merged.append(tokens[i] + tokens[i + 1])
            i += 2
        else:
            merged.append(tokens[i])
            i += 1

    return " ".join(merged)


def scrape_category(category_slug: str, category_name: str, max_page: int, sleep_s: float = 0.6) -> pd.DataFrame:
    rows = []

    for page in range(1, max_page + 1):
        url = (
            f"{BASE}companies/categories/{category_slug}.html"
            if page == 1
            else f"{BASE}companies/categories/{category_slug}.html?page={page}"
        )
        print(f"Scraping page {page:02d} -> {url}")

        soup = get_soup(url)
        cards = extract_cards(soup)
        print(f"  Cards trouvées: {len(cards)}")

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

            rows.append({
                "startup_name": startup_name,
                "tagline": tagline,
                "detail_url": detail_url,
                "category": category_name,
                "list_page": page
            })

        time.sleep(sleep_s)

    df = pd.DataFrame(rows).drop_duplicates(subset=["startup_name", "detail_url"]).reset_index(drop=True)
    return df


def main():
    parser = argparse.ArgumentParser(description="Scrape FrenchCleantech companies by category.")
    parser.add_argument("--category-slug", required=True,
                        help="FrenchCleantech category slug (e.g. energy-generation).")
    parser.add_argument("--category-name", default="",
                        help="Human readable category name (optional).")
    parser.add_argument("--max-page", type=int, default=1,
                        help="Number of pages to scrape (default: 1).")
    parser.add_argument("--sleep", type=float, default=0.6,
                        help="Delay between pages in seconds (default: 0.6).")
    parser.add_argument("--outdir", default=os.path.join("data", "raw"),
                        help="Output directory (default: data/raw).")

    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    # Fichiers de sortie (dépendent du slug => doivent être construits ici)
    path_raw = os.path.join(args.outdir, f"frenchcleantech_{args.category_slug}.csv")
    path_companies = os.path.join(args.outdir, f"frenchcleantech_{args.category_slug}_companies.csv")

    category_name = args.category_name.strip() or args.category_slug

    df = scrape_category(args.category_slug, category_name, args.max_page, sleep_s=args.sleep)
    print("Scraping terminé | Nb lignes (avant dédup entreprise):", len(df))

    df["name_clean"] = df["startup_name"].apply(normalize_company_name)
    df["name_clean_v2"] = df["startup_name"].apply(normalize_company_name_v2)

    df_companies = (
        df.sort_values("list_page", ascending=True)
          .drop_duplicates(subset=["name_clean_v2"])
          .reset_index(drop=True)
    ).copy()

    print("Nb entreprises uniques:", len(df_companies))
    print("Doublons restants (doit être 0):", df_companies["name_clean_v2"].duplicated().sum())

    df.to_csv(path_raw, index=False, encoding="utf-8-sig")
    df_companies.to_csv(path_companies, index=False, encoding="utf-8-sig")

    print("RAW sauvegardé:", path_raw)
    print("COMPANIES sauvegardé:", path_companies)


if __name__ == "__main__":
    main()