import os
import argparse
from urllib.parse import quote_plus

import pandas as pd


INPI_BASE_URL = "https://data.inpi.fr/search"


def build_inpi_link(company_name: str) -> str:
    """
    Construit une URL de recherche INPI à partir du nom d'une entreprise.
    """
    if not isinstance(company_name, str) or not company_name.strip():
        return ""
    query = quote_plus(company_name.strip())
    return f"{INPI_BASE_URL}?q={query}"


def main():
    parser = argparse.ArgumentParser(
        description="Génère des liens de recherche INPI à partir de la colonne startup_name."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Chemin du CSV en entrée (doit contenir la colonne startup_name).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Chemin du CSV en sortie (avec la colonne inpi_search_url).",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input)

    if "startup_name" not in df.columns:
        raise ValueError("Le CSV en entrée doit contenir une colonne 'startup_name'.")

    df["inpi_search_url"] = df["startup_name"].apply(build_inpi_link)

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    df.to_csv(args.output, index=False, encoding="utf-8-sig")

    print("Liens INPI générés")
    print("Input :", args.input)
    print("Output:", args.output)


if __name__ == "__main__":
    main()
