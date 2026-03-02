#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import argparse
import pandas as pd


def detect_separator(path: str, encoding: str = "utf-8-sig") -> str:
    """
    Détecte le séparateur principal entre ',' et ';'
    à partir du header et de quelques lignes.
    """
    with open(path, "r", encoding=encoding, errors="replace") as f:
        sample = f.read(50_000)

    comma = sample.count(",")
    semi = sample.count(";")
    return "," if comma >= semi else ";"


def safe_read_csv(path: str, dtype=str) -> pd.DataFrame:
    """
    Lecture robuste d'un CSV :
    - détection automatique du séparateur
    - gestion de plusieurs encodages
    - ignore les lignes corrompues
    """
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            sep = detect_separator(path, encoding=enc)
            df = pd.read_csv(
                path,
                dtype=dtype,
                sep=sep,
                engine="python",
                on_bad_lines="skip",
                encoding=enc,
            ).fillna("")
            return df
        except Exception:
            continue

    df = pd.read_csv(
        path,
        dtype=dtype,
        sep=",",
        engine="python",
        on_bad_lines="skip",
        encoding="utf-8-sig",
    ).fillna("")
    return df


def to_int_or_na(x):
    """
    Convertit une valeur en entier ou retourne NA si invalide.
    """
    x = "" if x is None else str(x).strip()
    if x == "" or x.lower() == "nan":
        return pd.NA
    try:
        return int(float(x))
    except Exception:
        return pd.NA


def main():
    parser = argparse.ArgumentParser(
        description="Construction du dataset final à partir du master RNE et des brevets."
    )
    parser.add_argument("--master", default="data/processed/frenchcleantech_master_rne.csv")
    parser.add_argument("--patents", default="data/processed/frenchcleantech_master_rne_patents.csv")
    parser.add_argument("--out", default="data/raw/frenchcleantech_final.csv")
    args = parser.parse_args()

    master = safe_read_csv(args.master, dtype=str)
    patents = safe_read_csv(args.patents, dtype=str)

    if "siren" not in master.columns:
        raise RuntimeError("Le fichier master doit contenir la colonne : siren")
    if "siren" not in patents.columns:
        raise RuntimeError("Le fichier patents doit contenir la colonne : siren")

    if "patents_total" not in patents.columns:
        patents["patents_total"] = ""

    patents_small = patents[["siren", "patents_total"]].copy()
    patents_small["siren"] = patents_small["siren"].astype(str).str.strip()
    patents_small["patents_total_num"] = patents_small["patents_total"].apply(to_int_or_na)
    patents_small = patents_small.drop_duplicates(subset=["siren"], keep="first")

    before_rows = len(master)
    master["siren"] = master["siren"].astype(str).str.strip()

    df = master.merge(
        patents_small[["siren", "patents_total_num"]],
        on="siren",
        how="left",
    )

    if len(df) != before_rows:
        raise RuntimeError(
            f"Le merge a modifié le nombre de lignes : avant={before_rows}, après={len(df)}"
        )

    df["patents_total"] = df["patents_total_num"]
    df = df.drop(columns=["patents_total_num"], errors="ignore")

    df["has_patent"] = df["patents_total"].apply(
        lambda v: pd.NA if pd.isna(v) else (1 if int(v) > 0 else 0)
    )

    if "match_status" in df.columns:
        df["match_found"] = (
            df["match_status"]
            .astype(str)
            .str.strip()
            .str.upper()
            .eq("OK")
            .astype(int)
        )
    else:
        df["match_found"] = pd.NA

    cols_to_drop = [
        "match_score",
        "rne_etat_administratif",
        "rne_date_creation",
        "rne_date_cessation",
        "match_query",
        "match_error",
        "rne_error",
        "cessation_source",
        "siret",
        "naf",
        "name_clean",
        "name_clean_v2",
        "denomination",
        "list_page",
    ]
    df = df.drop(columns=[c for c in cols_to_drop if c in df.columns], errors="ignore")

    preferred_order = [
        "startup_name",
        "tagline",
        "detail_url",
        "siren",
        "category",
        "match_status",
        "match_found",
        "survival",
        "etat_administratif",
        "date_creation",
        "date_cessation",
        "patents_total",
        "has_patent",
        "person_block",
    ]

    remaining = [c for c in df.columns if c not in preferred_order]
    df = df[[c for c in preferred_order if c in df.columns] + remaining]

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    df.to_csv(args.out, index=False, encoding="utf-8-sig")

    print("Saved:", args.out)
    print("Rows:", df.shape[0], "| Cols:", df.shape[1])

    if "match_status" in df.columns:
        print("match_status counts:\n", df["match_status"].value_counts(dropna=False))

    if "match_found" in df.columns:
        print("match_found counts:\n", df["match_found"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
