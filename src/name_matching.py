import re
import unicodedata
import argparse
from difflib import SequenceMatcher

import pandas as pd


LEGAL_FORMS = {
    "SAS", "SASU", "SARL", "SA", "SNC", "EURL", "GIE",
    "LTD", "LIMITED", "INC", "CORP", "CORPORATION",
    "BV", "GMBH", "SPA", "SRL"
}

COMMON_TOKENS = {
    "GROUPE", "GROUP", "HOLDING", "FRANCE", "INTERNATIONAL", "INTL",
    "COMPANY", "CO", "SOC", "SOCIETE", "ET", "ETABLISSEMENTS"
}


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def normalize_company_name(name: str) -> str:
    """
    Normalisation standard pour noms d'entreprises :
    - uppercase
    - suppression accents
    - suppression ponctuation
    - suppression formes juridiques
    - suppression tokens très fréquents
    """
    if not isinstance(name, str):
        return ""

    x = name.upper().strip()
    x = strip_accents(x)
    x = re.sub(r"[^A-Z0-9]", " ", x)      # garder lettres/chiffres
    x = re.sub(r"\s+", " ", x).strip()

    tokens = []
    for t in x.split():
        if t in LEGAL_FORMS:
            continue
        if t in COMMON_TOKENS:
            continue
        tokens.append(t)

    return " ".join(tokens)


def similarity(a: str, b: str) -> float:
    """
    Similarité simple entre deux chaînes normalisées.
    Retourne un score entre 0 et 1.
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def main():
    parser = argparse.ArgumentParser(description="Test basic name normalization and similarity.")
    parser.add_argument("--input", required=True, help="CSV containing a column startup_name.")
    parser.add_argument("--col", default="startup_name", help="Column name containing company names.")
    parser.add_argument("--n", type=int, default=10, help="Number of rows to preview.")

    args = parser.parse_args()

    df = pd.read_csv(args.input)

    if args.col not in df.columns:
        raise ValueError(f"Column '{args.col}' not found in input CSV.")

    df["name_normalized"] = df[args.col].apply(normalize_company_name)

    print(df[[args.col, "name_normalized"]].head(args.n).to_string(index=False))

    # Petit test de similarité sur les 2 premières lignes si possible
    if len(df) >= 2:
        a = df.loc[0, "name_normalized"]
        b = df.loc[1, "name_normalized"]
        print("\nExample similarity between first two normalized names:")
        print(f"  1) {a}")
        print(f"  2) {b}")
        print(f"  score = {similarity(a, b):.3f}")


if __name__ == "__main__":
    main()
