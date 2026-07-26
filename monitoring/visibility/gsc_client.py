"""Google Search Console API — клиент для Visibility Monitor V1.

Чистый httpx + cryptography (для подписи JWT сервис-аккаунта), без google-*.
Две схемы авторизации:
  - Service account (рекомендуется): подписываем RS256-JWT приватным ключом,
    меняем на access_token (server-to-server, без браузера, не протухает).
  - OAuth refresh-token: меняем refresh_token на access_token.
Наружу НИКОГДА не бросает: при ошибке/без ключей возвращает {} и логирует.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import time
import urllib.parse
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SC_BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


# ── авторизация ──────────────────────────────────────────────────────────────
def _post_retry(url: str, data: dict, attempts: int = 3, timeout: int = 30) -> dict:
    """POST токен-эндпоинта с ретраями (устойчивость к сетевым флапам)."""
    last = None
    for _ in range(attempts):
        try:
            r = httpx.post(url, data=data, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5)
    raise last if last else RuntimeError("token post failed")


def _access_token_refresh(client_id: str, client_secret: str, refresh_token: str) -> Optional[str]:
    try:
        return _post_retry(TOKEN_URL, {
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        }).get("access_token")
    except Exception as e:  # noqa: BLE001
        logger.error(f"[GSC] refresh-token exchange failed: {e}")
        return None


def _b64u(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _access_token_sa(sa: dict) -> Optional[str]:
    """Подписываем RS256-JWT приватным ключом сервис-аккаунта и меняем на access_token."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        token_uri = sa.get("token_uri", TOKEN_URL)
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": sa["client_email"],
            "scope": SCOPE,
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        }
        signing_input = _b64u(json.dumps(header).encode()) + b"." + _b64u(json.dumps(claims).encode())
        key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
        sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        assertion = (signing_input + b"." + _b64u(sig)).decode()

        return _post_retry(token_uri, {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }).get("access_token")
    except Exception as e:  # noqa: BLE001
        logger.error(f"[GSC] service-account token failed: {e}")
        return None


def load_service_account(inline_json: Optional[str], file_path: Optional[str]) -> Optional[dict]:
    """Достаёт SA-словарь из inline-JSON (env) или из файла. None если нет/битый."""
    raw = None
    if inline_json and inline_json.strip().startswith("{"):
        raw = inline_json
    elif file_path:
        try:
            with open(file_path, encoding="utf-8") as f:
                raw = f.read()
        except Exception as e:  # noqa: BLE001
            logger.error(f"[GSC] cannot read SA file: {e}")
            return None
    if not raw:
        return None
    try:
        sa = json.loads(raw)
        if sa.get("client_email") and sa.get("private_key"):
            return sa
    except Exception as e:  # noqa: BLE001
        logger.error(f"[GSC] bad SA json: {e}")
    return None


# ── запросы ──────────────────────────────────────────────────────────────────
def _query(token: str, site_url: str, body: dict) -> list[dict]:
    site = urllib.parse.quote(site_url, safe="")
    url = f"{SC_BASE}/{site}/searchAnalytics/query"
    try:
        r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        r.raise_for_status()
        return r.json().get("rows", []) or []
    except Exception as e:  # noqa: BLE001
        logger.error(f"[GSC] searchAnalytics query failed: {e}")
        return []


def _row(r: dict) -> dict:
    return {
        "impressions": int(r.get("impressions", 0) or 0),
        "clicks": int(r.get("clicks", 0) or 0),
        "ctr": float(r.get("ctr", 0.0) or 0.0),
        "position": float(r.get("position", 0.0) or 0.0),
    }


def _collect(token: str, site_url: str, days: int, row_limit: int) -> dict:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    sd, ed = start.isoformat(), end.isoformat()

    def rows(dimensions: list[str], limit: int) -> list[dict]:
        return _query(token, site_url, {
            "startDate": sd, "endDate": ed, "dimensions": dimensions, "rowLimit": limit,
        })

    by_date = [{"date": r["keys"][0], **_row(r)} for r in rows(["date"], 1000) if r.get("keys")]
    top_queries = [{"key": r["keys"][0], **_row(r)} for r in rows(["query"], row_limit) if r.get("keys")]
    top_pages = [{"key": r["keys"][0], **_row(r)} for r in rows(["page"], row_limit) if r.get("keys")]
    return {
        "by_date": by_date, "top_queries": top_queries, "top_pages": top_pages,
        "range": {"start": sd, "end": ed},
    }


# ── публичные точки входа ────────────────────────────────────────────────────
def fetch(site_url, client_id, client_secret, refresh_token, days: int = 30, row_limit: int = 200) -> dict:
    """OAuth refresh-token flow. {} если не настроено/ошибка."""
    if not (site_url and client_id and client_secret and refresh_token):
        return {}
    token = _access_token_refresh(client_id, client_secret, refresh_token)
    return _collect(token, site_url, days, row_limit) if token else {}


def fetch_sa(site_url, sa: Optional[dict], days: int = 30, row_limit: int = 200) -> dict:
    """Service-account flow. {} если не настроено/ошибка."""
    if not (site_url and sa):
        return {}
    token = _access_token_sa(sa)
    return _collect(token, site_url, days, row_limit) if token else {}
