import os
import time
import argparse
from urllib.parse import quote_plus

import pandas as pd
import requests


API_BASE = "https://recherche-entreprises.api.gouv.fr/search"
HEADERS = {"User-Agent": "startup-patents-survival/1.0"}


def search_company(name: str, limit: int = 5) -> dict:
    """Query the public 'API Recherche d’Entreprises' and return JSON results."""
    if not isinstance(name, str) or not name.strip():
        return {"results": []}

    q = name.strip()
    url = f"{API_BASE}?q={quote_plus(q)}&limite={limit}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def pick_best_result(results: list) -> dict:
    """
    Heuristique baseline:
    - si vide -> {}
    - sinon -> premier résultat (souvent correct si query bien nettoyée)
    """
    if not results:
        return {}
    return results[0]


def main():
    parser = argparse.ArgumentParser(
        description="Enrich master dataset with SIREN using recherche-entreprises.api.gouv.fr"
    )
    parser.add_argument("--input", required=True, help="Input master CSV (must contain startup_name, name_clean_v2).")
    parser.add_argument("--output", required=True, help="Output master CSV enriched with SIREN.")
    parser.add_argument("--sleep", type=float, default=0.25, help="Delay between requests (seconds).")
    parser.add_argument("--limit", type=int, default=5, help="Number of API results to fetch per query.")
    parser.add_argument("--resume", action="store_true", help="Skip rows that already have a siren (resume mode).")
    args = parser.parse_args()

    df = pd.read_csv(args.input, dtype=str).fillna("")

    required = {"startup_name", "name_clean_v2"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input CSV missing columns: {sorted(missing)}")

    # Assure colonnes target existent
    for col in ["siren", "siret", "denomination", "naf", "match_score", "match_status", "match_query", "match_error"]:
        if col not in df.columns:
            df[col] = ""

    total = len(df)

    for i, row in df.iterrows():
        startup_name = row.get("startup_name", "")
        name_clean_v2 = row.get("name_clean_v2", "")

        # mode reprise
        if args.resume and str(row.get("siren", "")).strip():
            print(f"[{i+1}/{total}] SKIP (has siren): {startup_name}")
            continue

        # query prioritaire : name_clean_v2, sinon startup_name
        query = name_clean_v2.strip() or startup_name.strip()
        df.at[i, "match_query"] = query

        print(f"[{i+1}/{total}] Searching: {startup_name} | query='{query}'")

        try:
            data = search_company(query, limit=args.limit)
            results = data.get("results", []) or []
            best = pick_best_result(results)

            if not best:
                df.at[i, "match_status"] = "NOT_FOUND"
                df.at[i, "match_score"] = ""
                df.at[i, "siren"] = ""
                df.at[i, "siret"] = ""
                df.at[i, "denomination"] = ""
                df.at[i, "naf"] = ""
            else:
                df.at[i, "siren"] = best.get("siren", "") or ""
                df.at[i, "siret"] = best.get("siret", "") or ""
                df.at[i, "denomination"] = best.get("nom_raison_sociale", best.get("denomination", "")) or ""
                df.at[i, "naf"] = best.get("naf", "") or ""
                df.at[i, "match_score"] = str(best.get("score", "")) if best.get("score", "") != "" else ""
                df.at[i, "match_status"] = "OK"

            df.at[i, "match_error"] = ""

        except Exception as e:
            df.at[i, "match_status"] = "ERROR"
            df.at[i, "match_error"] = str(e)[:500]
            # on vide les champs en cas d'erreur
            df.at[i, "siren"] = ""
            df.at[i, "siret"] = ""
            df.at[i, "denomination"] = ""
            df.at[i, "naf"] = ""
            df.at[i, "match_score"] = ""

        time.sleep(args.sleep)

        # sauvegarde progressive (sécurité)
        if (i + 1) % 25 == 0:
            os.makedirs(os.path.dirname(args.output), exist_ok=True)
            df.to_csv(args.output, index=False, encoding="utf-8-sig")
            print(f"Checkpoint saved ({i+1}/{total}): {args.output}")

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print("Saved:", args.output, "| rows:", len(df), "| OK:", (df["match_status"] == "OK").sum())


if __name__ == "__main__":
    main()