import os
import re
import json
import time
import argparse
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv


BASE_RNE = "https://registre-national-entreprises.inpi.fr"
LOGIN_URL = f"{BASE_RNE}/api/sso/login"
COMPANY_URL = f"{BASE_RNE}/api/companies/{{siren}}"

SIREN_RE = re.compile(r"^\d{9}$")


def pick_env(*names: str) -> Optional[str]:
    """
    Retourne la première variable d'environnement non vide parmi celles fournies.
    """
    for n in names:
        v = os.getenv(n)
        if v and str(v).strip():
            return str(v).strip()
    return None


def get_in(d: Any, path: List[str]) -> Any:
    """
    Accès sécurisé à un dictionnaire imbriqué.
    """
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def first_non_empty(*vals):
    """
    Retourne la première valeur non vide.
    """
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def parse_date_loose(s: Optional[str]) -> Optional[str]:
    """
    Valide grossièrement un format de date RNE (YYYY-MM-DD ou YYYY-MM) et renvoie la chaîne.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            _ = datetime.strptime(s, fmt)
            return s
        except ValueError:
            pass
    return s


def login_get_token(session: requests.Session, username: str, password: str) -> str:
    """
    Login RNE et récupération du token.
    """
    r = session.post(LOGIN_URL, json={"username": username, "password": password}, timeout=30)
    r.raise_for_status()
    data = r.json()
    token = data.get("token")
    if not token:
        raise RuntimeError("Login OK mais token absent dans la réponse.")
    return token


def fetch_company_json(session: requests.Session, token: str, siren: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Récupère le JSON RNE pour un SIREN.
    """
    headers = {"Authorization": f"Bearer {token}"}
    url = COMPANY_URL.format(siren=siren)
    r = session.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_company_json_retry(
    session: requests.Session,
    token: str,
    siren: str,
    retries: int = 3,
    base_sleep: float = 1.0,
    timeout: int = 30,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Requête RNE avec retries sur erreurs réseau.
    Retourne (json, erreur).
    """
    for attempt in range(1, retries + 1):
        try:
            js = fetch_company_json(session, token, siren, timeout=timeout)
            return js, None
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            return None, f"HTTP {status}: {str(e)}"
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == retries:
                return None, f"NETWORK: {type(e).__name__}: {str(e)[:200]}"
            time.sleep(base_sleep * (2 ** (attempt - 1)))
        except Exception as e:
            return None, f"ERROR: {type(e).__name__}: {str(e)[:200]}"
    return None, "ERROR: unexpected retry loop end"


def extract_survival_fields(company_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrait les champs utiles (dates, état, survival) depuis le JSON RNE.
    """
    siren = company_json.get("siren")

    formality = company_json.get("formality", {}) if isinstance(company_json.get("formality"), dict) else {}
    content = formality.get("content", {}) if isinstance(formality.get("content"), dict) else {}

    date_creation = parse_date_loose(get_in(content, ["natureCreation", "dateCreation"]))

    person_block = None
    if isinstance(content.get("personneMorale"), dict):
        person_block = "personneMorale"
    elif isinstance(content.get("personnePhysique"), dict):
        person_block = "personnePhysique"
    elif isinstance(content.get("exploitation"), dict):
        person_block = "exploitation"

    dce = get_in(content, [person_block, "detailCessationEntreprise"]) if person_block else None

    date_cessation = None
    cessation_source = None

    if isinstance(dce, dict):
        candidates = [
            ("dateRadiation", dce.get("dateRadiation")),
            ("dateCessationTotaleActivite", dce.get("dateCessationTotaleActivite")),
            ("dateClotureLiquidation", dce.get("dateClotureLiquidation")),
            ("dateDissolutionDisparition", dce.get("dateDissolutionDisparition")),
            ("dateTransfertPatrimoine", dce.get("dateTransfertPatrimoine")),
            ("dateCessationActiviteSalariee", dce.get("dateCessationActiviteSalariee")),
            ("dateMiseEnSommeil", dce.get("dateMiseEnSommeil")),
        ]
        for k, v in candidates:
            v2 = parse_date_loose(v) if isinstance(v, str) else None
            if v2:
                date_cessation = v2
                cessation_source = k
                break

    evenement_cessation = content.get("evenementCessation")
    nature_cessation = content.get("natureCessation")

    if date_cessation or evenement_cessation or nature_cessation:
        etat_administratif = "CESSATION"
        survival = 0
    else:
        etat_administratif = "ACTIVE"
        survival = 1

    return {
        "siren": siren,
        "person_block": person_block,
        "etat_administratif": etat_administratif,
        "date_creation": date_creation,
        "date_cessation": date_cessation,
        "cessation_source": cessation_source,
        "survival": survival,
        "updatedAt": company_json.get("updatedAt"),
    }


def is_valid_siren(x: str) -> bool:
    """
    Valide un SIREN (9 chiffres).
    """
    if not isinstance(x, str):
        return False
    x = x.strip()
    return bool(SIREN_RE.match(x))


def main():
    parser = argparse.ArgumentParser(
        description="Enrichit un CSV avec les champs RNE (état administratif, dates, survival)."
    )
    parser.add_argument("--input", required=True, help="CSV en entrée (startup_name + siren).")
    parser.add_argument("--output", required=True, help="Chemin du CSV en sortie.")
    parser.add_argument(
        "--dump-json-dir",
        default="",
        help="Si renseigné, sauvegarde les réponses JSON brutes (un fichier par siren).",
    )
    parser.add_argument("--limit", type=int, default=0, help="Si >0, traite uniquement les N premières lignes.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Pause entre requêtes (secondes).")
    parser.add_argument("--retries", type=int, default=3, help="Retries sur erreurs réseau.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Ignore les lignes déjà enrichies (date_creation ou survival déjà rempli).",
    )
    args = parser.parse_args()

    load_dotenv()

    username = pick_env("INPI_USERNAME", "INPI_EMAIL")
    password = pick_env("INPI_PASSWORD")
    if not username or not password:
        raise RuntimeError("INPI_EMAIL/INPI_PASSWORD manquants dans le fichier .env")

    df = pd.read_csv(args.input, dtype=str).fillna("")
    if "startup_name" not in df.columns or "siren" not in df.columns:
        raise ValueError("Le fichier input doit contenir 'startup_name' et 'siren'.")

    if args.limit and args.limit > 0:
        df = df.head(args.limit).copy()

    for col in [
        "etat_administratif",
        "date_creation",
        "date_cessation",
        "cessation_source",
        "survival",
        "person_block",
        "rne_error",
    ]:
        if col not in df.columns:
            df[col] = ""

    dump_dir = args.dump_json_dir.strip()
    if dump_dir:
        os.makedirs(dump_dir, exist_ok=True)

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with requests.Session() as session:
        token = login_get_token(session, username, password)

        total = len(df)
        for i, row in df.iterrows():
            startup_name = row.get("startup_name", "").strip()
            siren = row.get("siren", "").strip()

            if args.resume and (row.get("survival", "").strip() or row.get("date_creation", "").strip()):
                print(f"[{i+1}/{total}] SKIP (déjà enrichi) {startup_name} ({siren})")
                continue

            if not is_valid_siren(siren):
                df.at[i, "etat_administratif"] = ""
                df.at[i, "date_creation"] = ""
                df.at[i, "date_cessation"] = ""
                df.at[i, "cessation_source"] = ""
                df.at[i, "survival"] = ""
                df.at[i, "person_block"] = ""
                df.at[i, "rne_error"] = "NO_SIREN"
                print(f"[{i+1}/{total}] {startup_name} (NO_SIREN)")
                continue

            print(f"[{i+1}/{total}] {startup_name} ({siren})")

            js, err = fetch_company_json_retry(
                session,
                token,
                siren,
                retries=args.retries,
                base_sleep=1.0,
                timeout=30,
            )

            if err or js is None:
                print(f"  -> ERROR: {err}")
                df.at[i, "rne_error"] = err or "UNKNOWN_ERROR"
                time.sleep(args.sleep)
                continue

            if dump_dir:
                with open(os.path.join(dump_dir, f"{siren}.json"), "w", encoding="utf-8") as f:
                    json.dump(js, f, ensure_ascii=False, indent=2)

            fields = extract_survival_fields(js)
            df.at[i, "etat_administratif"] = fields["etat_administratif"] or ""
            df.at[i, "date_creation"] = fields["date_creation"] or ""
            df.at[i, "date_cessation"] = fields["date_cessation"] or ""
            df.at[i, "cessation_source"] = fields["cessation_source"] or ""
            df.at[i, "survival"] = str(fields["survival"]) if fields["survival"] is not None else ""
            df.at[i, "person_block"] = fields["person_block"] or ""
            df.at[i, "rne_error"] = ""

            time.sleep(args.sleep)

            if (i + 1) % 25 == 0:
                df.to_csv(args.output, index=False, encoding="utf-8-sig")
                print(f"Checkpoint saved ({i+1}/{total}): {args.output}")

    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print("Saved:", args.output)


if __name__ == "__main__":
    main()
