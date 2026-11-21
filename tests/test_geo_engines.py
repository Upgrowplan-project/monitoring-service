"""[21.11 · владелец «да — помоги»] monitoring/geo_engines.py + ряды GEO с поиском в geo_visibility_task.

Правило (до кода): ответ «ссылается на сайт» (cited) — среди источников ответа есть upgrowplan.com; «упоминает» (mentioned) —
название в тексте. Отказ по квоте/ключу/оплате — одна запись с причиной, ряд этой нейросети на сегодня остановлен,
остальные ряды продолжают. Ряд «gemini» (без поиска) не меняется. Образец OpenAI — живой ответ 21.11 (сокращён)."""
import os

import pytest

from monitoring import geo_engines as GE
from monitoring import tasks

OPENAI_LIVE = {"output": [
    {"type": "web_search_call", "status": "completed"},
    {"type": "message", "content": [{"type": "output_text",
                                     "text": "Conducting effective market research is crucial for small businesses...",
                                     "annotations": [
                                         {"type": "url_citation", "url": "https://startupik.com/best-ai-tools-for-market-research/?utm_source=openai"},
                                         {"type": "url_citation", "url": "https://zapier.com/blog/best-rank-tracker/?utm_source=openai"},
                                         {"type": "url_citation", "url": "https://startupik.com/best-ai-tools-for-market-research/?utm_source=openai"}]}]}],
    "usage": {"input_tokens": 8174, "output_tokens": 588}}
GEMINI_GROUNDED = {"candidates": [{"content": {"parts": [{"text": "Try Upgrowplan for local competitor prices."}]},
                                   "groundingMetadata": {"groundingChunks": [
                                       {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbC", "title": "upgrowplan.com"}},
                                       {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/XyZ", "title": "zapier.com"}}],
                                       "webSearchQueries": ["best ai market research tools"]}}]}
PERPLEXITY_DOC = {"output": [
    {"type": "search_results", "results": [{"url": "https://www.upgrowplan.com/blog/ai-market-research-vs-traditional"},
                                           {"url": "https://example.com/x"}]},
    {"type": "message", "content": [{"type": "output_text", "text": "Several tools exist..."}]}]}


def test_parsers_and_cited():
    t, s = GE.parse_openai(OPENAI_LIVE)
    assert t.startswith("Conducting") and len(s) == 2 and not GE.cited(s)            # повтор ссылки схлопнут
    t, s = GE.parse_gemini(GEMINI_GROUNDED)
    assert "Upgrowplan" in t and GE.cited(s)                                           # домен — в title у Gemini
    t, s = GE.parse_perplexity(PERPLEXITY_DOC)
    assert t == "Several tools exist..." and GE.cited(s)
    with pytest.raises(GE.EngineError):
        GE.parse_openai({"output": [{"type": "web_search_call"}]})


def test_enabled_needs_key_and_gemini_switch(monkeypatch):
    for k in ("GEO_ENGINES", "GEO_GEMINI_SEARCH", "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cfg = type("C", (), {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o"})
    assert GE.enabled(cfg) == ["chatgpt_search"]                                       # Gemini с поиском — выключен
    monkeypatch.setenv("GEO_GEMINI_SEARCH", "on")
    assert GE.enabled(cfg) == ["gemini_search", "chatgpt_search"]
    monkeypatch.setenv("GEO_ENGINES", "chatgpt_search")
    assert GE.enabled(cfg) == ["chatgpt_search"]


def test_ask_maps_errors():
    cfg = type("C", (), {"OPENAI_API_KEY": "o"})
    seen = {}

    def ok(url, headers, body, timeout):
        seen.update(url=url, body=body)
        return 200, OPENAI_LIVE
    r = GE.ask("chatgpt_search", "q", cfg, post=ok)
    assert seen["url"].endswith("/v1/responses") and seen["body"]["tools"] == [{"type": "web_search"}] and r["cited"] is False
    for code, kind in ((429, "quota"), (401, "quota"), (402, "quota"), (500, "http")):
        with pytest.raises(GE.EngineError) as ei:
            GE.ask("chatgpt_search", "q", cfg, post=lambda *a, c=code: (c, {"error": {"message": "x"}}))
        assert ei.value.kind == kind


def test_scan_adds_search_series_and_quota_stops_only_that_series(monkeypatch):
    from contextlib import contextmanager
    saved = []

    class DB:
        def add_all(self, rows):
            saved.extend(rows)

        def commit(self):
            pass

    @contextmanager
    def session():
        yield DB()
    monkeypatch.setattr(tasks, "get_db_session", session)
    monkeypatch.setattr(tasks, "_geo_auto_scan_done_today", lambda n: False)
    monkeypatch.setattr(tasks, "_gemini_post", lambda k, p: "plain answer without the brand")
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: None)
    monkeypatch.setattr(tasks, "get_config", lambda: type("C", (), {"GEMINI_API_KEY": "g", "OPENAI_API_KEY": "o",
                                                                     "PERPLEXITY_API_KEY": "p", "GEO_BRAND": "upgrowplan"})())
    for k in ("GEO_ENGINES", "GEO_GEMINI_SEARCH"):
        monkeypatch.delenv(k, raising=False)
    calls = {"chatgpt_search": 0, "perplexity_search": 0}

    def fake_ask(engine, query, cfg=None, post=None):
        calls[engine] += 1
        if engine == "perplexity_search":
            raise GE.EngineError("quota", "HTTP 402: no credits")
        return {"text": "See Upgrowplan.", "sources": ["https://www.upgrowplan.com/about"], "cited": True}
    monkeypatch.setattr(GE, "ask", fake_ask)
    res = tasks.geo_visibility_task(force=True)
    by = {}
    for r in saved:
        by.setdefault(r.llm, []).append(r)
    n = len(by["gemini"])                                                              # ряд без поиска — как раньше
    assert n >= 6 and all(r.cited is None for r in by["gemini"])
    assert len(by["chatgpt_search"]) == n and all(r.cited and r.mentioned for r in by["chatgpt_search"])
    assert calls["perplexity_search"] == 1 and len(by["perplexity_search"]) == 1          # отказ — одна запись, ряд стоп
    assert by["perplexity_search"][0].response_text.startswith("[ERROR: quota_exceeded] Perplexity")
    assert res["status"] == "ok"


def test_api_summary_counts_cited():
    import main
    from fastapi.testclient import TestClient
    from monitoring.database import Base, SessionLocal, engine
    from monitoring.models import GeoCheck
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(GeoCheck).delete()
    db.add_all([GeoCheck(llm="chatgpt_search", query="Best AI market research tools", response_text="x", mentioned=True,
                         cited=True, sources=["https://www.upgrowplan.com/about"]),
                GeoCheck(llm="chatgpt_search", query="Best AI business plan generator", response_text="y", mentioned=False,
                         cited=False, sources=["https://zapier.com"]),
                GeoCheck(llm="gemini", query="Best AI market research tools", response_text="z", mentioned=False)])
    db.commit()
    db.close()
    os.environ["MONITORING_READ_TOKEN"] = "test-read"
    j = TestClient(main.app).get("/api/monitoring/geo", headers={"X-Read-Token": "test-read"}).json()
    s = j["summary"]
    assert s["chatgpt_search"]["total"] == 2 and s["chatgpt_search"]["mentioned"] == 1 and s["chatgpt_search"]["cited"] == 1
    assert s["chatgpt_search"]["with_search"] is True and s["gemini"]["with_search"] is False
    assert any(i["cited"] and i["sources"] for i in j["items"])
