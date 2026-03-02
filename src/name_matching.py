import re
import unicodedata
import argparse
from difflib import SequenceMatcher

import pandas as pd


LEGAL_FORMS = {
    "SAS", "SASU", "SARL", "SA", "SNC", "EURL", "GIE",
    "LTD", "LIMITED", "INC", "CORP", "CORPORATION",
    "BV", "GMBH", "SPA", "SRL",
}

COMMON_TOKENS = {
    "GROUPE", "GROUP", "HOLDING", "FRANCE", "INTERNATIONAL", "INTL",
    "COMPANY", "CO", "SOC", "SOCIETE", "ET", "ETABLISSEMENTS",
}


def strip_accents(s: str) -> str:
    """
    Supprime les accents d'une chaîne.
    """
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def normalize_company_name(name: str) -> str:
    """
    Normalise un nom d'entreprise :
    - majuscules, accents supprimés
    - ponctuation remplacée par des espaces
    - suppression des formes juridiques et tokens très fréquents
    """
    if not isinstance(name, str):
        return ""

    x = name.upper().strip()
    x = strip_accents(x)
    x = re.sub(r"[^A-Z0-9]", " ", x)
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
    Calcule une similarité (0 à 1) entre deux chaînes.
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def main():
    parser = argparse.ArgumentParser(
        description="Teste une normalisation simple de noms d'entreprises et un score de similarité."
    )
    parser.add_argument("--input", required=True, help="CSV en entrée contenant une colonne de noms.")
    parser.add_argument("--col", default="startup_name", help="Nom de la colonne contenant les noms.")
    parser.add_argument("--n", type=int, default=10, help="Nombre de lignes à afficher.")

    args = parser.parse_args()

    df = pd.read_csv(args.input)

    if args.col not in df.columns:
        raise ValueError(f"Colonne '{args.col}' introuvable dans le CSV.")

    df["name_normalized"] = df[args.col].apply(normalize_company_name)

    print(df[[args.col, "name_normalized"]].head(args.n).to_string(index=False))

    if len(df) >= 2:
        a = df.loc[0, "name_normalized"]
        b = df.loc[1, "name_normalized"]
        print("\nExemple de similarité entre les deux premiers noms normalisés :")
        print(f"  1) {a}")
        print(f"  2) {b}")
        print(f"  score = {similarity(a, b):.3f}")


if __name__ == "__main__":
    main()
