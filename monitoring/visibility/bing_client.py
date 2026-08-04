"""Bing Webmaster Tools API — клиент для Visibility Monitor V1.

Чистый httpx, авторизация через apikey. Важно для GEO: ChatGPT-поиск грундится
на Bing, поэтому Bing-метрики — ближайший реальный прокси к AI-выдаче.
Наружу не бросает: при ошибке/без ключа возвращает {}.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE = "https://ssl.bing.com/webmaster/api.svc/json"
_DATE_RE = re.compile(r"/Date\((\d+)")


def _parse_ms_date(value) -> Optional[dt.datetime]:
    """Bing отдаёт даты как '/Date(1610000000000)/' (мс от эпохи, иногда +смещение)."""
    if not value:
        return None
    m = _DATE_RE.search(str(value))
    if not m:
        return None
    try:
        return dt.datetime.utcfromtimestamp(int(m.group(1)) / 1000.0)
    except Exception:  # noqa: BLE001
        return None


def _get(method: str, apikey: str, site_url: str, extra: Optional[dict] = None) -> list:
    params = {"apikey": apikey, "siteUrl": site_url}
    if extra:
        params.update(extra)
    try:
        r = httpx.get(f"{BASE}/{method}", params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        d = data.get("d", []) if isinstance(data, dict) else []
        return d or []
    except Exception as e:  # noqa: BLE001
        logger.error(f"[Bing] {method} failed: {e}")
        return []


def _num(v) -> int:
    try:
        return int(v or 0)
    except Exception:  # noqa: BLE001
        return 0


def fetch(site_url: Optional[str], apikey: Optional[str], days: int = 30) -> dict:
    """Возвращает {by_date, top_queries, top_pages} или {} если не настроено."""
    if not (site_url and apikey):
        return {}
    apikey = apikey.strip()  # env vars sometimes have trailing newline

    cutoff = dt.date.today() - dt.timedelta(days=days)

    # Дневной трафик (impressions/clicks по дням)
    by_date = []
    for it in _get("GetRankAndTrafficStats", apikey, site_url):
        d = _parse_ms_date(it.get("Date"))
        if not d or d.date() < cutoff:
            continue
        impr, clk = _num(it.get("Impressions")), _num(it.get("Clicks"))
        by_date.append({
            "date": d.date().isoformat(),
            "impressions": impr,
            "clicks": clk,
            "ctr": (clk / impr) if impr else 0.0,
            "position": float(it.get("AvgImpressionPosition") or 0) or None,
        })

    def rows(method: str, key_field: tuple[str, ...]) -> list[dict]:
        out = []
        for it in _get(method, apikey, site_url):
            impr, clk = _num(it.get("Impressions")), _num(it.get("Clicks"))
            key = next((it.get(k) for k in key_field if it.get(k)), None)
            out.append({
                "key": key,
                "impressions": impr,
                "clicks": clk,
                "ctr": (clk / impr) if impr else 0.0,
                "position": float(it.get("AvgImpressionPosition") or 0) or None,
            })
        return out

    top_queries = rows("GetQueryStats", ("Query",))
    top_pages = rows("GetPageStats", ("Query", "Url", "Page"))

    return {"by_date": by_date, "top_queries": top_queries, "top_pages": top_pages}
