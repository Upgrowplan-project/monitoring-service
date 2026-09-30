"""
GEO: переходы людей на сайт из ответов нейросетей (AI-referral).

Это НЕ визиты краулеров (те пишет middleware в BotCrawlEvent). Здесь — pageview
от JS-маячка фронта, т.е. браузер человека, который кликнул ссылку в ответе
ChatGPT/Perplexity/… Источник определяется по:
  - utm_source: ChatGPT сам дописывает ?utm_source=chatgpt.com к цитируемым ссылкам;
  - домену реферера: Perplexity, Claude (веб), Gemini, Copilot передают Referer.
Текст запроса пользователя нейросети не передают — его в данных нет и быть не может.

Модуль чистый (без БД): на вход — список событий-словарей, на выход — агрегаты.
Единственное место, где задан список AI-источников (SSOT): им же пользуется
/api/monitoring/analytics, чтобы не показывать эти переходы в SEO-списке UTM.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urlparse

# (название, домены реферера, значения utm_source)
AI_SOURCES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("ChatGPT", ("chatgpt.com", "chat.openai.com"), ("chatgpt.com", "chatgpt", "chat.openai.com", "openai")),
    ("Perplexity", ("perplexity.ai",), ("perplexity.ai", "perplexity")),
    ("Gemini", ("gemini.google.com", "bard.google.com"), ("gemini.google.com", "gemini", "bard")),
    ("Copilot", ("copilot.microsoft.com", "copilot.cloud.microsoft"), ("copilot.microsoft.com", "copilot")),
    ("Claude", ("claude.ai",), ("claude.ai", "claude")),
    ("DeepSeek", ("chat.deepseek.com",), ("deepseek", "chat.deepseek.com")),
    ("Grok", ("grok.com",), ("grok", "grok.com")),
    ("Mistral", ("chat.mistral.ai",), ("mistral", "chat.mistral.ai")),
    ("Meta AI", ("meta.ai",), ("meta.ai",)),
    ("You.com", ("you.com",), ("you.com",)),
]


def _host(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def classify_ai_source(utm_source: Optional[str], referrer: Optional[str]) -> Optional[str]:
    """Название нейросети, если визит пришёл из неё; иначе None."""
    utm = (utm_source or "").strip().lower()
    host = _host(referrer)
    for name, hosts, utms in AI_SOURCES:
        if utm and utm in utms:
            return name
        if host and any(host == h or host.endswith("." + h) for h in hosts):
            return name
    return None


def _iso(v) -> Optional[str]:
    return v.isoformat() if isinstance(v, datetime) else (v or None)


def build_ai_referrals(events: Iterable[dict], visit_limit: int = 200) -> dict:
    """
    events — pageview-события периода (любого происхождения), поля как у WebEvent:
    created_at, path, referrer, utm_source, utm_medium, utm_campaign, session_id,
    visitor_id, device_type, browser, os, locale, timezone, country, locale_url.

    Визит = сессия, в которой есть хотя бы один pageview из нейросети.
    Точка входа — первый такой pageview; страницы визита — все pageview этой
    сессии начиная с точки входа.
    """
    rows = sorted(events, key=lambda e: e["created_at"])

    first_seen_visitor: dict[str, datetime] = {}
    sessions: "OrderedDict[str, list[dict]]" = OrderedDict()
    for i, e in enumerate(rows):
        vid = e.get("visitor_id")
        if vid and vid not in first_seen_visitor:
            first_seen_visitor[vid] = e["created_at"]
        # Без session_id событие — отдельный «визит» из одного просмотра.
        sid = e.get("session_id") or f"__nosession_{i}"
        sessions.setdefault(sid, []).append(e)

    visits: list[dict] = []
    for sid, evs in sessions.items():
        landing_idx = next(
            (k for k, e in enumerate(evs) if classify_ai_source(e.get("utm_source"), e.get("referrer"))),
            None,
        )
        if landing_idx is None:
            continue
        land = evs[landing_idx]
        tail = evs[landing_idx:]
        vid = land.get("visitor_id")
        visits.append({
            "source": classify_ai_source(land.get("utm_source"), land.get("referrer")),
            "started_at": _iso(land["created_at"]),
            "landing_path": land.get("path"),
            "landing_url": land.get("locale_url"),
            "referrer": land.get("referrer"),
            "utm_source": land.get("utm_source"),
            "utm_medium": land.get("utm_medium"),
            "utm_campaign": land.get("utm_campaign"),
            "pages": [e.get("path") for e in tail],
            "pages_count": len(tail),
            "duration_sec": int((tail[-1]["created_at"] - land["created_at"]).total_seconds()),
            "returning_visitor": bool(vid and first_seen_visitor.get(vid) and first_seen_visitor[vid] < land["created_at"]),
            "visitor_id": (vid or "")[:8] or None,
            "device_type": land.get("device_type"),
            "browser": land.get("browser"),
            "os": land.get("os"),
            "locale": land.get("locale"),
            "timezone": land.get("timezone"),
            "country": land.get("country"),
        })

    visits.sort(key=lambda v: v["started_at"] or "", reverse=True)

    by_source: dict[str, dict] = {}
    landing: dict[tuple[str, str], int] = {}
    for v in visits:
        s = by_source.setdefault(v["source"], {"visits": 0, "pageviews": 0, "visitors": set()})
        s["visits"] += 1
        s["pageviews"] += v["pages_count"]
        if v["visitor_id"]:
            s["visitors"].add(v["visitor_id"])
        key = (v["landing_path"] or "", v["source"])
        landing[key] = landing.get(key, 0) + 1

    return {
        "total_visits": len(visits),
        "by_source": [
            {
                "source": name,
                "visits": s["visits"],
                "unique_visitors": len(s["visitors"]),
                "pageviews": s["pageviews"],
                "pages_per_visit": round(s["pageviews"] / s["visits"], 2) if s["visits"] else 0,
            }
            for name, s in sorted(by_source.items(), key=lambda kv: -kv[1]["visits"])
        ],
        "landing_pages": [
            {"path": p, "source": src, "visits": n}
            for (p, src), n in sorted(landing.items(), key=lambda kv: -kv[1])
        ],
        "visits": visits[:visit_limit],
    }
