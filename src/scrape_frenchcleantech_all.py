#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import argparse
import unicodedata
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# URL racine du site French Cleantech
BASE = "https://www.frenchcleantech.com/"

# En-têtes HTTP standards pour limiter les blocages côté serveur
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,fr-FR;q=0.8,fr;q=0.7",
}


def _make_session() -> requests.Session:
    """
    Crée une session requests avec une politique de retry.
    L’objectif est de gérer les erreurs temporaires (ex: 429, 5xx) lors des requêtes GET.
    """
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(DEFAULT_HEADERS)
    return session


_SESSION = _make_session()


def get_soup(url: str, timeout: int = 30, sleep_on_403: float = 0.0) -> BeautifulSoup:
    """
    Télécharge une page HTML et retourne un objet BeautifulSoup.

    - timeout : délai max en secondes
    - sleep_on_403 : pause optionnelle en cas de 403 (protection / anti-bot)
    """
    resp = _SESSION.get(url, timeout=timeout)
    if resp.status_code == 403 and sleep_on_403 > 0:
        time.sleep(sleep_on_403)
        resp = _SESSION.get(url, timeout=timeout)

    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def clean_text(text: str) -> str:
    """Nettoie un texte en supprimant les espaces multiples et les caractères non standards."""
    if text is None:
        return ""
    s = text.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_accents(s: str) -> str:
    """Supprime les accents d’une chaîne (normalisation Unicode)."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


# Termes juridiques fréquents à retirer dans une normalisation agressive
_LEGAL = {
    "SAS", "SASU", "SARL", "EURL", "SA", "SCI", "SNC", "SCOP", "SCIC",
    "ASSOCIATION", "ASSO", "GIE", "SEM", "ETS", "ETABLISSEMENTS",
    "HOLDING", "GROUPE", "GROUP",
    "LTD", "LIMITED", "INC", "CORP", "CORPORATION", "LLC", "PLC", "GMBH", "BV",
    "CO", "COMPANY",
}

# Stopwords simples pour améliorer le dédoublonnage
_STOP = {
    "DE", "DU", "DES", "LA", "LE", "LES", "D", "L", "ET", "A", "AU", "AUX",
    "EN", "SUR", "SOUS", "CHEZ", "THE", "OF", "AND",
}


def normalize_company_name(name: str) -> str:
    """
    Normalisation conservatrice d’un nom d’entreprise.
    Objectif : limiter les différences typographiques sans trop modifier le contenu.
    """
    s = clean_text(name).upper()
    s = _strip_accents(s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"[_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_company_name_v2(name: str) -> str:
    """
    Normalisation plus agressive, utilisée pour le dédoublonnage.
    Retire certains termes juridiques et stopwords.
    """
    s = normalize_company_name(name)
    if not s:
        return ""

    tokens = []
    for t in s.split():
        if len(t) <= 1:
            continue
        if t in _LEGAL:
            continue
        if t in _STOP:
            continue
        tokens.append(t)

    return " ".join(tokens).strip()


def extract_cards(soup: BeautifulSoup):
    """
    Extrait les cartes d’entreprises d’une page catégorie.

    Sortie : liste de tuples (bloc_html, lien_read_more)
    Le script utilise ensuite :
    - le titre (h1/h2/h3) trouvé dans le bloc
    - l’URL du lien "Read more"
    """
    cards = []

    readmore_links = soup.find_all("a", string=re.compile(r"read\s+more", re.I))
    for a in readmore_links:
        name_tag = a.find_previous(["h1", "h2", "h3"])
        if name_tag is not None and name_tag.parent is not None:
            block = name_tag.parent
        else:
            block = a.parent if a.parent is not None else soup
        cards.append((block, a))

    if not cards:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href:
                continue
            if "/companies/" in href and ("categories/" not in href):
                name_tag = a.find_previous(["h1", "h2", "h3"])
                block = name_tag.parent if name_tag and name_tag.parent else (a.parent or soup)
                cards.append((block, a))

    return cards


COMPANIES_URL = urljoin(BASE, "companies.html")


def list_categories() -> list[tuple[str, str]]:
    """
    Récupère la liste des catégories (slug, label) depuis companies.html.
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

    if not found:
        html = soup.decode()
        slugs = sorted(set(m.group(1).lower() for m in pattern.finditer(html)))
        found = {s: s for s in slugs}

    return sorted(found.items(), key=lambda x: x[0])


def scrape_category_autopage(category_slug: str, category_name: str, max_page: int, sleep_s: float) -> pd.DataFrame:
    """
    Scrape une catégorie avec auto-pagination.

    - max_page > 0 : limite volontaire (debug)
    - max_page == 0 : continue jusqu’à page vide ou absence de nouvelles URL
    """
    rows = []
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

        if new_added == 0:
            print(f"  STOP: aucune nouvelle entreprise détectée à page={page}.")
            break

        time.sleep(sleep_s)
        page += 1

    df = pd.DataFrame(rows).drop_duplicates(subset=["startup_name", "detail_url"]).reset_index(drop=True)
    return df


def main():
    """
    Point d’entrée.
    - Détecte les catégories
    - Scrape chaque catégorie
    - Exporte deux CSV : brut (toutes lignes) et entreprises uniques
    """
    parser = argparse.ArgumentParser(description="Scrape ALL FrenchCleantech categories (auto-pagination robuste).")
    parser.add_argument("--max-page", type=int, default=0, help="Max pages par catégorie. 0 = autopagination.")
    parser.add_argument("--sleep", type=float, default=0.6, help="Pause entre pages (secondes).")
    parser.add_argument("--outdir", default=os.path.join("data", "raw"), help="Dossier de sortie (défaut: data/raw).")
    parser.add_argument("--limit-categories", type=int, default=0, help="Si >0, scrape uniquement les N premières catégories.")
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
        raise RuntimeError("Aucune donnée scrapée. Vérifier la structure du site et la connexion.")

    df_all["name_clean"] = df_all["startup_name"].apply(normalize_company_name)
    df_all["name_clean_v2"] = df_all["startup_name"].apply(normalize_company_name_v2)

    path_raw_all = os.path.join(args.outdir, "frenchcleantech_all.csv")
    df_all.drop_duplicates(subset=["startup_name", "detail_url", "category"]).to_csv(
        path_raw_all, index=False, encoding="utf-8-sig"
    )

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
