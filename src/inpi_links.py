import os
import argparse
from urllib.parse import quote_plus

import pandas as pd


INPI_BASE_URL = "https://data.inpi.fr/search"


def build_inpi_link(company_name: str) -> str:
    """
    Build a robust INPI search URL from a company name.
    """
    if not isinstance(company_name, str) or not company_name.strip():
        return ""
    query = quote_plus(company_name.strip())
    return f"{INPI_BASE_URL}?q={query}"


def main():
    parser = argparse.ArgumentParser(description="Generate INPI search links for companies.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input CSV containing startup_name column."
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output CSV with INPI links."
    )

    args = parser.parse_args()

    df = pd.read_csv(args.input)

    if "startup_name" not in df.columns:
        raise ValueError("Input CSV must contain a 'startup_name' column.")

    df["inpi_search_url"] = df["startup_name"].apply(build_inpi_link)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")

    print("INPI links generated")
    print("Input :", args.input)
    print("Output:", args.output)


if __name__ == "__main__":
    main()