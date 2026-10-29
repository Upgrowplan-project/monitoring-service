"""
[29.10 · owner «1–5»] GEO scan through Gemini: no successful answer since 25.10.
Measured 29.10: the alias gemini-flash-latest → gemini-3.8-flash, free tier 20 requests/day; the scan ran on every wake
of the eco dyno (30–65 rows/day for 12 queries) and called any 429 «daily limit» after two more attempts.
"""
import io
import json
import urllib.error
from contextlib import contextmanager

import pytest

from monitoring import tasks

DAILY_429 = json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
    {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
         "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]},
    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "9951s"}]}})
MINUTE_429 = json.dumps({"error": {"code": 429, "details": [
    {"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaValue": "15"}]},
    {"retryDelay": "7s"}]}})


def http_error(code, body=""):
    return urllib.error.HTTPError("https://g", code, "x", {}, io.BytesIO(body.encode()))


class FakeDB:
    def __init__(self, texts):
        self.texts, self.added = texts, []

    def query(self, *a):
        return self

    def filter(self, *a):
        return self

    def all(self):
        return [(t,) for t in self.texts]

    def add_all(self, rows):
        self.added.extend(rows)

    def commit(self):
        pass


@pytest.fixture
def scan(monkeypatch):
    """Runs one forced scan against scripted Gemini answers; returns (result, saved rows, calls, sleeps)."""
    def run(answers, today=()):
        db = FakeDB(list(today))

        @contextmanager
        def session():
            yield db

        calls, sleeps = [], []

        def post(key, prompt):
            calls.append(prompt)
            a = answers.pop(0) if answers else "Upgrowplan is a planning service."
            if isinstance(a, Exception):
                raise a
            return a

        monkeypatch.setattr(tasks, "get_db_session", session)
        monkeypatch.setattr(tasks, "_gemini_post", post)
        monkeypatch.setattr(tasks.time if hasattr(tasks, "time") else __import__("time"), "sleep", lambda s: sleeps.append(s))
        monkeypatch.setattr(tasks, "get_config", lambda: type("C", (), {"GEMINI_API_KEY": "k", "GEO_BRAND": "upgrowplan"})())
        return run.force(db, calls, sleeps)

    def force_run(db, calls, sleeps):
        return tasks.geo_visibility_task(force=run.forced), db.added, calls, sleeps

    run.force, run.forced = force_run, True
    return run


def test_model_is_pinned_and_switchable(monkeypatch):
    monkeypatch.delenv("GEO_GEMINI_MODEL", raising=False)
    assert "/models/gemini-3.5-flash-lite:generateContent" in tasks._get_gemini_url()
    monkeypatch.setenv("GEO_GEMINI_MODEL", "gemini-3.5-flash")
    assert "/models/gemini-3.5-flash:generateContent" in tasks._get_gemini_url()


def test_quota_info_reads_google_429():
    q = tasks._geo_quota_info(DAILY_429)
    assert q["quota_id"] == "GenerateRequestsPerDayPerProjectPerModel-FreeTier" and q["limit"] == "20" and q["retry_s"] == 9951
    assert tasks._geo_quota_info("not json") == {"quota_id": "", "limit": None, "retry_s": None}


def test_daily_quota_stops_at_once_and_says_which(scan):
    res, rows, calls, sleeps = scan([http_error(429, DAILY_429)])
    assert len(calls) == 1 and sleeps == [] and res["status"] == "quota_exceeded"
    assert len(rows) == 1 and "Суточный лимит" in rows[0].response_text and "20 запросов" in rows[0].response_text


def test_minute_quota_waits_as_google_asks(scan):
    res, rows, calls, sleeps = scan([http_error(429, MINUTE_429), "answer"])
    assert sleeps[0] == 7 and len(calls) >= 2 and not rows[0].response_text.startswith("[ERROR")


def test_high_demand_503_is_retried_once(scan):
    res, rows, calls, sleeps = scan([http_error(503, '{"error":{"message":"high demand"}}'), "answer"])
    assert calls[0] == calls[1] and 20 in sleeps and not rows[0].response_text.startswith("[ERROR")


def test_second_503_is_reported(scan):
    res, rows, calls, sleeps = scan([http_error(503), http_error(503)])
    assert calls[0] == calls[1] and rows[0].response_text.startswith("[ERROR: http_503]")


@pytest.mark.parametrize("today,skip", [
    ([], False),
    (["[ERROR: http_503] x"] * 3, False),            # only transient errors so far → one more automatic try
    (["Upgrowplan is ..."], True),                     # a successful answer today
    (["[ERROR: quota_exceeded] Суточный ..."], True),  # the daily quota is gone
    (["[ERROR: exception] timeout"] * 24, True),       # two scans' worth already
])
def test_automatic_scan_once_a_day(monkeypatch, today, skip):
    db = FakeDB(today)

    @contextmanager
    def session():
        yield db

    monkeypatch.setattr(tasks, "get_db_session", session)
    assert tasks._geo_auto_scan_done_today(12) is skip


def test_scheduler_skips_but_button_forces(monkeypatch):
    seen = []
    monkeypatch.setattr(tasks, "_geo_auto_scan_done_today", lambda n: True)
    monkeypatch.setattr(tasks, "get_config", lambda: type("C", (), {"GEMINI_API_KEY": "k", "GEO_BRAND": "upgrowplan"})())
    monkeypatch.setattr(tasks, "_gemini_post", lambda k, p: seen.append(p) or "x")
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: None)

    @contextmanager
    def session():
        yield FakeDB([])

    monkeypatch.setattr(tasks, "get_db_session", session)
    assert tasks.geo_visibility_task()["status"] == "skipped" and seen == []
    res = tasks.geo_visibility_task(force=True)
    # 6 or 12 questions depending on the day's rotation group — the button sends all of them
    assert res["status"] == "ok" and len(seen) in (6, 12) and res["saved"] == len(seen)
