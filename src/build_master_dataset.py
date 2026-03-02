import os
import argparse
import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description="Construit le dataset master à partir du scraping FrenchCleantech."
    )
    parser.add_argument(
        "--input",
        default=os.path.join("data", "raw", "frenchcleantech_all_companies.csv"),
        help="CSV en entrée (par défaut : data/raw/frenchcleantech_all_companies.csv)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join("data", "processed", "frenchcleantech_master.csv"),
        help="CSV en sortie (par défaut : data/processed/frenchcleantech_master.csv)",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input, dtype=str).fillna("")

    # Déduplication sur name_clean_v2 (une ligne par startup)
    df = (
        df.sort_values(["category", "list_page"], ascending=True)
        .drop_duplicates(subset=["name_clean_v2"], keep="first")
        .reset_index(drop=True)
    )

    # Ajoute les colonnes nécessaires aux étapes suivantes du pipeline
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
