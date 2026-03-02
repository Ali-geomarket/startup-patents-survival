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
    Interroge l'API Recherche d’Entreprises et retourne le JSON.
    """
    if not isinstance(name, str) or not name.strip():
        return {"results": []}

    q = name.strip()
    url = f"{API_BASE}?q={quote_plus(q)}&limite={limit}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def pick_best_result(results: list) -> dict:
    """
    Sélection simple : prend le premier résultat si présent.
    """
    if not results:
        return {}
    return results[0]


def main():
    parser = argparse.ArgumentParser(
        description="Enrichit un master CSV avec le SIREN via recherche-entreprises.api.gouv.fr"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="CSV en entrée (doit contenir startup_name, name_clean_v2).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="CSV en sortie enrichi (SIREN, SIRET, NAF, etc.).",
    )
    parser.add_argument("--sleep", type=float, default=0.25, help="Pause entre requêtes (secondes).")
    parser.add_argument("--limit", type=int, default=5, help="Nombre de résultats récupérés par requête.")
    parser.add_argument("--resume", action="store_true", help="Ignore les lignes qui ont déjà un SIREN.")
    args = parser.parse_args()

    df = pd.read_csv(args.input, dtype=str).fillna("")

    required = {"startup_name", "name_clean_v2"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes dans le CSV : {sorted(missing)}")

    for col in [
        "siren",
        "siret",
        "denomination",
        "naf",
        "match_score",
        "match_status",
        "match_query",
        "match_error",
    ]:
        if col not in df.columns:
            df[col] = ""

    total = len(df)

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    for i, row in df.iterrows():
        startup_name = row.get("startup_name", "")
        name_clean_v2 = row.get("name_clean_v2", "")

        if args.resume and str(row.get("siren", "")).strip():
            print(f"[{i+1}/{total}] SKIP (déjà un SIREN) : {startup_name}")
            continue

        query = name_clean_v2.strip() or startup_name.strip()
        df.at[i, "match_query"] = query

        print(f"[{i+1}/{total}] Recherche : {startup_name} | query='{query}'")

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
                score = best.get("score", "")
                df.at[i, "match_score"] = str(score) if score != "" else ""
                df.at[i, "match_status"] = "OK"

            df.at[i, "match_error"] = ""

        except Exception as e:
            df.at[i, "match_status"] = "ERROR"
            df.at[i, "match_error"] = str(e)[:500]
            df.at[i, "siren"] = ""
            df.at[i, "siret"] = ""
            df.at[i, "denomination"] = ""
            df.at[i, "naf"] = ""
            df.at[i, "match_score"] = ""

        time.sleep(args.sleep)

        if (i + 1) % 25 == 0:
            df.to_csv(args.output, index=False, encoding="utf-8-sig")
            print(f"Checkpoint saved ({i+1}/{total}) : {args.output}")

    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    ok_count = (df["match_status"] == "OK").sum() if "match_status" in df.columns else 0
    print("Saved:", args.output, "| rows:", len(df), "| OK:", ok_count)


if __name__ == "__main__":
    main()
