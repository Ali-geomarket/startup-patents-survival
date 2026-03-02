import os
import argparse
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description="Build master dataset from FrenchCleantech scraped companies.")
    parser.add_argument(
        "--input",
        default=os.path.join("data", "raw", "frenchcleantech_all_companies.csv"),
        help="Input CSV (default: data/raw/frenchcleantech_all_companies.csv)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join("data", "processed", "frenchcleantech_master.csv"),
        help="Output CSV (default: data/processed/frenchcleantech_master.csv)",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input, dtype=str).fillna("")

    # Dédup robuste : priorité au name_clean_v2, sinon detail_url
    df = (
        df.sort_values(["category", "list_page"], ascending=True)
          .drop_duplicates(subset=["name_clean_v2"], keep="first")
          .reset_index(drop=True)
    )

    # Colonnes "master" + placeholders pour la suite du pipeline
    out = df.copy()
    for col in [
        "siren",
        "match_status",
        "match_score",
        "rne_etat_administratif",
        "rne_date_creation",
        "rne_date_cessation",
        "survival",
        "patents_total",
        "has_patent",
    ]:
        if col not in out.columns:
            out[col] = ""

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    out.to_csv(args.output, index=False, encoding="utf-8-sig")
    print("Saved:", args.output, "| rows:", len(out), "| cols:", len(out.columns))


if __name__ == "__main__":
    main()