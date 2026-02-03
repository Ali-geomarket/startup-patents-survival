import os
import time
import argparse
from urllib.parse import quote_plus

import pandas as pd
import requests


API_BASE = "https://recherche-entreprises.api.gouv.fr/search"
HEADERS = {"User-Agent": "startup-patents-survival/1.0"}


def search_company(name: str, limit: int = 5) -> dict:
    """
    Query the public 'API Recherche d’Entreprises' and return JSON results.
    """
    if not isinstance(name, str) or not name.strip():
        return {"results": []}

    q = name.strip()
    url = f"{API_BASE}?q={quote_plus(q)}&limite={limit}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def pick_best_result(results: list, query_name: str) -> dict:
    """
    Heuristique simple : prendre le premier résultat.
    On améliorera ensuite avec ton module de normalisation + similarité.
    """
    if not results:
        return {}
    return results[0]


def main():
    parser = argparse.ArgumentParser(description="Lookup SIREN for company names using a public API.")
    parser.add_argument("--input", required=True, help="Input CSV with startup_name column.")
    parser.add_argument("--output", required=True, help="Output CSV with SIREN candidates.")
    parser.add_argument("--sleep", type=float, default=0.25, help="Delay between requests (seconds).")
    parser.add_argument("--limit", type=int, default=5, help="Number of API results to fetch per query.")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    if "startup_name" not in df.columns:
        raise ValueError("Input CSV must contain a 'startup_name' column.")

    rows = []
    for i, name in enumerate(df["startup_name"].fillna("").astype(str), start=1):
        print(f"[{i}/{len(df)}] Searching: {name}")

        try:
            data = search_company(name, limit=args.limit)
            results = data.get("results", []) or data.get("results", [])
            best = pick_best_result(results, name)

            rows.append({
                "startup_name": name,
                "siren": best.get("siren", ""),
                "siret": best.get("siret", ""),
                "denomination": best.get("nom_raison_sociale", best.get("denomination", "")),
                "naf": best.get("naf", ""),
                "score_api": best.get("score", ""),  # si présent
            })
        except Exception as e:
            rows.append({
                "startup_name": name,
                "siren": "",
                "siret": "",
                "denomination": "",
                "naf": "",
                "score_api": "",
                "error": str(e),
            })

        time.sleep(args.sleep)

    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    print("Saved:", args.output)


if __name__ == "__main__":
    main()