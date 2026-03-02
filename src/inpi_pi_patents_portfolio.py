import os
import time
import argparse
import socket
from typing import Optional, Dict, Tuple

import requests
import pandas as pd
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_HOST = "api-gateway.inpi.fr"

UAA_AUTHENTICATE = f"https://{API_HOST}/services/uaa/api/authenticate"
AUTH_LOGIN = f"https://{API_HOST}/auth/login"
BREVETS_SEARCH = f"https://{API_HOST}/services/apidiffusion/api/brevets/search"

UA_HEADERS_BASE = {
    "accept": "application/json",
    "user-agent": "Mozilla/5.0",
    "x-forwarded-for": "127.0.0.1",
}


def make_session(retries: int = 5, backoff: float = 0.8) -> requests.Session:
    """
    Crée une session Requests avec retry sur erreurs réseau et HTTP 5xx.
    """
    s = requests.Session()
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def dns_precheck(host: str = API_HOST) -> str:
    """
    Vérifie que le host est résolu par DNS.
    """
    return socket.gethostbyname(host)


def is_valid_siren(x: str) -> bool:
    """
    Valide un SIREN (9 chiffres).
    """
    return isinstance(x, str) and x.isdigit() and len(x) == 9


def get_xsrf(session: requests.Session) -> str:
    """
    Récupère le token XSRF depuis les cookies de session.
    """
    xsrf = session.cookies.get("XSRF-TOKEN")
    if not xsrf:
        raise RuntimeError("Cookie XSRF-TOKEN introuvable (session invalide ou login non fait).")
    return xsrf


def build_cookie_header(session: requests.Session) -> Optional[str]:
    """
    Construit le header Cookie attendu par l'API (selon cookies présents).
    """
    xsrf = session.cookies.get("XSRF-TOKEN")
    access_token = session.cookies.get("access_token")
    session_token = session.cookies.get("session_token")
    refresh_token = session.cookies.get("refresh_token")

    parts = []
    if xsrf:
        parts.append(f"XSRF-TOKEN={xsrf}")
    if access_token:
        parts.append(f"access_token={access_token}")
    if session_token:
        parts.append(f"session_token={session_token}")
    elif refresh_token:
        parts.append(f"session_token={refresh_token}")

    return "; ".join(parts) if parts else None


def build_headers(session: requests.Session) -> Dict[str, str]:
    """
    Construit les headers nécessaires pour les appels POST (dont XSRF + cookies).
    """
    xsrf = get_xsrf(session)
    h = dict(UA_HEADERS_BASE)
    h["content-type"] = "application/json"
    h["x-xsrf-token"] = xsrf

    ck = build_cookie_header(session)
    if ck:
        h["Cookie"] = ck

    h["Connection"] = "close"
    return h


def is_quota_429(resp: requests.Response) -> bool:
    """
    Détecte un 429 lié au quota (et pas un autre cas).
    """
    if resp.status_code != 429:
        return False
    txt = (resp.text or "").lower()
    return ("quota" in txt) or ("too many requests" in txt) or ("exhaust" in txt)


def get_retry_after_seconds(resp: requests.Response) -> int:
    """
    Lit Retry-After si présent, sinon retourne 0.
    """
    ra = resp.headers.get("Retry-After")
    if not ra:
        return 0
    try:
        return int(float(ra))
    except Exception:
        return 0


def safe_atomic_csv_save(
    df: pd.DataFrame,
    out_path: str,
    retries: int = 5,
    sleep_s: float = 2.0,
) -> None:
    """
    Sauvegarde atomique (Windows/Excel) : écrit dans un .tmp puis remplace le fichier final.
    """
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    tmp_path = out_path + ".tmp"
    last_err = None

    for _ in range(retries):
        try:
            df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
            os.replace(tmp_path, out_path)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(sleep_s)
        except Exception as e:
            last_err = e
            break

    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception:
        pass

    raise last_err


def pi_authenticate_and_login(session: requests.Session, email: str, password: str) -> None:
    """
    Initialise la session INPI PI (authenticate puis login).
    """
    r1 = session.get(UAA_AUTHENTICATE, headers=UA_HEADERS_BASE, timeout=30)
    if r1.status_code >= 400 and r1.status_code != 401:
        raise RuntimeError(f"[authenticate] HTTP {r1.status_code} body={r1.text[:500]}")

    _ = get_xsrf(session)

    payload = {"username": email, "password": password, "rememberMe": True}
    r2 = session.post(
        AUTH_LOGIN,
        headers={**UA_HEADERS_BASE, "content-type": "application/json", "x-xsrf-token": get_xsrf(session)},
        json=payload,
        timeout=30,
    )
    if r2.status_code >= 400:
        raise RuntimeError(f"[login] HTTP {r2.status_code} body={r2.text[:800]}")


def _post_search(session: requests.Session, siren: str, size: int, position: int) -> requests.Response:
    """
    Envoie la requête POST de recherche brevets pour un SIREN.
    """
    body = {
        "collections": ["FR", "EP", "CCP"],
        "query": f"[TISI={siren}]",
        "size": size,
        "position": position,
    }
    headers = build_headers(session)
    return session.post(BREVETS_SEARCH, headers=headers, json=body, timeout=60)


def search_patents_count_post_only(
    session: requests.Session,
    siren: str,
    size: int = 1,
    position: int = 0,
) -> Tuple[Optional[int], str, Optional[requests.Response]]:
    """
    Retourne (count, status, resp).
    status = ok | quota | need_reset | http_error | parse_error
    """
    r = _post_search(session, siren, size=size, position=position)

    if r.status_code == 403 and "Invalid CSRF Token" in (r.text or ""):
        session.get(UAA_AUTHENTICATE, headers=UA_HEADERS_BASE, timeout=30)
        r = _post_search(session, siren, size=size, position=position)

    if is_quota_429(r):
        return None, "quota", r

    if r.status_code == 405:
        return None, "need_reset", r

    if r.status_code >= 400:
        return None, "http_error", r

    try:
        data = r.json()
        md = data.get("metadata", {}) if isinstance(data, dict) else {}
        if isinstance(md, dict) and md.get("count") is not None:
            return int(md["count"]), "ok", r

        results = data.get("results", []) if isinstance(data, dict) else []
        return int(len(results)), "ok", r
    except Exception:
        return None, "parse_error", r


def load_dataframe(input_path: str, output_path: str, resume: bool) -> pd.DataFrame:
    """
    Si resume et output existe : repart du fichier output, sinon du fichier input.
    """
    base_path = output_path if (resume and os.path.exists(output_path)) else input_path
    df = pd.read_csv(base_path, dtype=str).fillna("")
    if "patents_total" not in df.columns:
        df["patents_total"] = ""
    return df


def main():
    load_dotenv(".env")

    parser = argparse.ArgumentParser(
        description="INPI PI : récupère le nombre de brevets par SIREN (POST only + reprise + checkpoints)."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sleep", type=float, default=1.2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--wait-on-429",
        action="store_true",
        help="Attend et reprend sur HTTP 429 au lieu d'arrêter.",
    )
    parser.add_argument(
        "--wait-429-default",
        type=int,
        default=1800,
        help="Temps d'attente (s) si Retry-After absent (défaut : 1800).",
    )
    parser.add_argument(
        "--max-resets-per-row",
        type=int,
        default=2,
        help="Nombre max de resets session sur une même ligne (ex : erreur 405).",
    )
    args = parser.parse_args()

    email = os.getenv("INPI_PI_EMAIL")
    password = os.getenv("INPI_PI_PASSWORD")
    if not email or not password:
        raise RuntimeError("INPI_PI_EMAIL / INPI_PI_PASSWORD manquants dans le fichier .env")

    ip = dns_precheck(API_HOST)
    print(f"DNS OK: {API_HOST} -> {ip}")

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    df = load_dataframe(args.input, args.output, resume=args.resume)

    if "siren" not in df.columns or "startup_name" not in df.columns:
        raise RuntimeError("Le CSV doit contenir au moins : siren, startup_name (et idéalement patents_total).")

    if args.limit and args.limit > 0:
        df = df.head(args.limit).copy()

    total = len(df)
    processed_since_checkpoint = 0

    session = make_session(retries=5, backoff=0.9)
    pi_authenticate_and_login(session, email, password)
    print("Login OK. Cookies:", list(session.cookies.keys()))

    def reset_session():
        nonlocal session
        try:
            session.close()
        except Exception:
            pass
        session = make_session(retries=5, backoff=0.9)
        pi_authenticate_and_login(session, email, password)
        print("Session reset + login OK. Cookies:", list(session.cookies.keys()))

    try:
        for i, row in df.iterrows():
            name = (row.get("startup_name") or "").strip()
            siren = (row.get("siren") or "").strip()
            current_val = str(row.get("patents_total", "")).strip()

            if args.resume and current_val != "":
                print(f"[{i+1}/{total}] SKIP {name} ({siren})")
                continue

            if not is_valid_siren(siren):
                print(f"[{i+1}/{total}] {name} (NO_SIREN)")
                df.at[i, "patents_total"] = ""
                continue

            print(f"[{i+1}/{total}] {name} ({siren})")

            resets = 0
            while True:
                count, status, resp = search_patents_count_post_only(session, siren, size=1, position=0)

                if status == "ok":
                    df.at[i, "patents_total"] = str(count)
                    break

                if status == "quota":
                    safe_atomic_csv_save(df, args.output)
                    print("Saved checkpoint:", args.output)

                    if not args.wait_on_429:
                        print("STOP: quota INPI PI atteint (HTTP 429).")
                        print("Relance plus tard avec --resume (tu ne perdras rien).")
                        return

                    wait_s = get_retry_after_seconds(resp) if resp is not None else 0
                    if wait_s <= 0:
                        wait_s = args.wait_429_default
                    print(f"HTTP 429: pause {wait_s}s puis reprise...")
                    time.sleep(wait_s)
                    reset_session()
                    resets = 0
                    continue

                if resp is not None:
                    allow = resp.headers.get("Allow", "")
                    print(
                        f"  -> ERROR: status={resp.status_code} allow={allow} url={resp.url} body={resp.text[:160]}"
                    )
                else:
                    print("  -> ERROR: réponse inconnue")

                if resets < args.max_resets_per_row:
                    resets += 1
                    reset_session()
                    continue

                df.at[i, "patents_total"] = ""
                break

            processed_since_checkpoint += 1
            time.sleep(args.sleep)

            if args.checkpoint_every and processed_since_checkpoint >= args.checkpoint_every:
                safe_atomic_csv_save(df, args.output)
                print(f"Checkpoint saved: {args.output}")
                processed_since_checkpoint = 0

    finally:
        try:
            session.close()
        except Exception:
            pass

    safe_atomic_csv_save(df, args.output)
    print("Saved:", args.output)


if __name__ == "__main__":
    main()
