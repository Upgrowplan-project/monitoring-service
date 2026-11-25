"""[25.11 · владелец «давай (а)»] Пачка просмотров и заходов ИИ-роботов с сайта раз в сутки (/api/monitoring/events-batch):
без ключа — 401; просмотр сохраняет страну, браузер, отпечаток IP и настоящее время события; время из будущего не принимается;
строка без пути пропускается, остальные сохраняются; сбой записи — 500 и ни одной строки (сайт повторит пачку). Одиночный
beacon /pageview после выноса общей функции пишет то же, что раньше. Офлайн, временная SQLite (tests/conftest.py)."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-events-batch")
os.environ.setdefault("MONITORING_INGEST_TOKEN", "test-ingest")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def _client():
    import main
    from monitoring.database import Base, engine
    Base.metadata.create_all(bind=engine)
    return main, TestClient(main.app)


def _hdr():
    return {"X-Ingest-Token": os.environ["MONITORING_INGEST_TOKEN"]}


def _rows(model, **flt):
    from monitoring.database import SessionLocal
    db = SessionLocal()
    try:
        return db.query(model).filter_by(**flt).all()
    finally:
        db.close()


def test_batch_requires_ingest_token():
    _, c = _client()
    assert c.post("/api/monitoring/events-batch", json={"pageviews": []}).status_code == 401
    assert c.post("/api/monitoring/events-batch", json={"pageviews": []},
                  headers={"X-Ingest-Token": "wrong"}).status_code == 401


def test_batch_saves_pageviews_and_bot_crawls_with_event_time():
    main, c = _client()
    from monitoring.models import WebEvent, BotCrawlEvent
    at = (datetime.utcnow() - timedelta(hours=20)).replace(microsecond=0)
    future = (datetime.utcnow() + timedelta(days=2)).isoformat() + "Z"
    body = {
        "pageviews": [
            {"path": "/ru/batch-test-1", "url": "https://www.upgrowplan.com/ru/batch-test-1?utm_source=x&token=secret",
             "visitor_id": "v-batch", "session_id": "s-batch", "locale": "ru-RU", "timezone": "Asia/Jerusalem",
             "event_type": "pageview", "user_agent": CHROME, "ip_hash": "abc123", "country": "IL",
             "created_at": at.isoformat() + "Z"},
            {"path": "/ru/batch-test-future", "user_agent": CHROME, "created_at": future},
            {"url": "https://www.upgrowplan.com/no-path"},          # без пути — пропуск
        ],
        "bot_crawls": [
            {"bot_name": "GPTBot", "bot_raw_ua": "GPTBot/1.1", "url_path": "/blog/batch-test",
             "crawled_at": at.isoformat() + "Z"},
            {"bot_name": "", "url_path": "/blog/x"},                # без имени — пропуск
        ],
    }
    r = c.post("/api/monitoring/events-batch", json=body, headers=_hdr())
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "pageviews": 2, "bot_crawls": 1, "skipped": 2}

    pv = _rows(WebEvent, path="/ru/batch-test-1")
    assert len(pv) == 1
    row = pv[0]
    assert (row.country, row.ip_hash, row.browser, row.device_type) == ("IL", "abc123", "Chrome", "desktop")
    assert row.created_at == at                                   # настоящее время события, не время приёма
    assert "token=secret" not in (row.locale_url or "")           # очистка адреса — та же, что у beacon
    fut = _rows(WebEvent, path="/ru/batch-test-future")[0]
    assert fut.created_at <= datetime.utcnow()                    # будущее время не принимается

    bot = _rows(BotCrawlEvent, url_path="/blog/batch-test")
    assert len(bot) == 1 and bot[0].bot_name == "GPTBot" and bot[0].crawled_at == at


def test_batch_write_failure_saves_nothing(monkeypatch):
    main, c = _client()
    from monitoring.models import WebEvent
    calls = {"n": 0}
    real = main._web_event_row

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("db down")
        return real(*a, **kw)

    monkeypatch.setattr(main, "_web_event_row", flaky)
    body = {"pageviews": [{"path": "/ru/batch-fail-1", "user_agent": CHROME},
                          {"path": "/ru/batch-fail-2", "user_agent": CHROME}]}
    r = c.post("/api/monitoring/events-batch", json=body, headers=_hdr())
    assert r.status_code == 500
    assert _rows(WebEvent, path="/ru/batch-fail-1") == []          # первая строка тоже не записана


def test_batch_rejects_oversized_and_non_lists():
    main, c = _client()
    assert c.post("/api/monitoring/events-batch", json={"pageviews": "x"}, headers=_hdr()).status_code == 400
    big = {"pageviews": [{"path": "/p"}] * (main.EVENTS_BATCH_MAX + 1)}
    assert c.post("/api/monitoring/events-batch", json=big, headers=_hdr()).status_code == 413


def test_single_beacon_unchanged_after_refactor():
    _, c = _client()
    from monitoring.models import WebEvent
    r = c.post("/api/monitoring/pageview", json={"path": "/ru/beacon-single", "visitor_id": "v1"},
               headers={"user-agent": CHROME, "x-forwarded-for": "203.0.113.7, 10.0.0.1", "x-vercel-ip-country": "DE"})
    assert r.json() == {"ok": True}
    row = _rows(WebEvent, path="/ru/beacon-single")[0]
    import hashlib
    assert row.ip_hash == hashlib.sha256(b"upgrowplan-salt::203.0.113.7").hexdigest()[:32]
    assert (row.country, row.browser) == ("DE", "Chrome")
