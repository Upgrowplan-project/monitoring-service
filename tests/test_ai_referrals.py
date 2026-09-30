"""GEO: переходы из нейросетей (AI-referral) — классификатор и сборка визитов."""
import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ar = importlib.import_module("monitoring.ai_referrals")

T0 = datetime(2026, 9, 20, 10, 0, 0)


def ev(minutes, path, sid="s1", vid="v1", utm=None, ref=None, **kw):
    return {"created_at": T0 + timedelta(minutes=minutes), "path": path, "session_id": sid,
            "visitor_id": vid, "utm_source": utm, "referrer": ref, **kw}


@pytest.mark.parametrize("utm,ref,expected", [
    ("chatgpt.com", None, "ChatGPT"),
    ("ChatGPT.com ", None, "ChatGPT"),
    (None, "https://chatgpt.com/", "ChatGPT"),
    (None, "https://www.perplexity.ai/search/abc", "Perplexity"),
    (None, "https://gemini.google.com/app", "Gemini"),
    (None, "https://claude.ai/chat/1", "Claude"),
    (None, "https://copilot.microsoft.com/", "Copilot"),
])
def test_ai_sources_detected(utm, ref, expected):
    assert ar.classify_ai_source(utm, ref) == expected


@pytest.mark.parametrize("utm,ref", [
    (None, None),
    ("linkedin", None),
    ("newsletter", "https://www.google.com/"),
    (None, "https://www.bing.com/search?q=x"),        # поиск Bing — это SEO, не нейросеть
    (None, "https://notchatgpt.com/"),                # похожий домен не должен совпадать
    (None, "https://www.upgrowplan.com/blog"),
    ("meta", None),                                   # utm_source=meta — реклама Facebook, не Meta AI
    (None, "not a url"),
])
def test_non_ai_not_detected(utm, ref):
    assert ar.classify_ai_source(utm, ref) is None


def test_visit_starts_at_ai_landing_and_follows_session():
    events = [
        ev(0, "/", sid="old", vid="v1"),                                 # раньше: обычный визит того же человека
        ev(60, "/blog/milan", utm="chatgpt.com", locale="ru-RU", device_type="mobile",
           locale_url="https://www.upgrowplan.com/blog/milan?utm_source=chatgpt.com"),
        ev(61, "/solutions/marketResearch"),
        ev(64, "/ru/about"),
        ev(5, "/pricing", sid="s2", vid="v2"),                           # чужая сессия без AI
        ev(70, "/blog/x", sid="s3", vid="v3", ref="https://www.perplexity.ai/"),
    ]
    r = ar.build_ai_referrals(events)
    assert r["total_visits"] == 2
    gpt = next(v for v in r["visits"] if v["source"] == "ChatGPT")
    assert gpt["landing_path"] == "/blog/milan"
    assert gpt["pages"] == ["/blog/milan", "/solutions/marketResearch", "/ru/about"]
    assert gpt["pages_count"] == 3 and gpt["duration_sec"] == 240
    assert gpt["returning_visitor"] is True
    assert gpt["locale"] == "ru-RU" and gpt["device_type"] == "mobile"
    assert "utm_source=chatgpt.com" in gpt["landing_url"]
    ppx = next(v for v in r["visits"] if v["source"] == "Perplexity")
    assert ppx["returning_visitor"] is False and ppx["pages_count"] == 1
    assert {s["source"]: s["visits"] for s in r["by_source"]} == {"ChatGPT": 1, "Perplexity": 1}
    assert r["visits"][0]["source"] == "Perplexity"                     # свежие первыми


def test_pages_before_ai_landing_not_counted():
    events = [ev(0, "/"), ev(1, "/blog/a", utm="chatgpt.com"), ev(2, "/blog/b")]
    v = ar.build_ai_referrals(events)["visits"][0]
    assert v["pages"] == ["/blog/a", "/blog/b"]


def test_empty_and_no_session():
    assert ar.build_ai_referrals([])["total_visits"] == 0
    r = ar.build_ai_referrals([ev(0, "/a", sid=None, utm="chatgpt.com"), ev(1, "/b", sid=None, utm="chatgpt.com")])
    assert r["total_visits"] == 2                                       # без session_id — каждый просмотр отдельно
    assert sorted(r["landing_pages"], key=lambda x: x["path"]) == [
        {"path": "/a", "source": "ChatGPT", "visits": 1},
        {"path": "/b", "source": "ChatGPT", "visits": 1},
    ]
