"""[18.11 · владелец п.5 — «канарейка: DRA извлекает цены, ежедневно на 3 сайтах»] monitoring/dra_canary.py + dra_price_canary_task.

Правило (до кода): страница «есть цены» — facts_count ≥ 1; все 3 — healthy; 1–2 — degraded; 0 / ошибка DRA (в т.ч. тело
{"_dra_error": true} при HTTP 200 — keep-alive DRA) / нет ответа — down. Раз в сутки (UTC); неуспех — повтор не чаще раза в 6 ч.
Письмо — при смене состояния. База — временная (tests/conftest.py)."""
from datetime import datetime, timedelta

import pytest

from monitoring import dra_canary as DC


def _body(counts):
    return {"results": [{"url": u, "facts_count": n, "outcome": "fetched"} for u, n in zip(DC.PAGES, counts)],
            "total_facts": sum(counts), "outcome_counts": {"fetched": len(counts)}}


def test_evaluate_states():
    assert DC.evaluate(200, _body([10, 11, 10]))["status"] == "healthy"
    d = DC.evaluate(200, _body([10, 0, 10]))
    assert d["status"] == "degraded" and "noesis-pilates.com" in d["error_message"] and d["metadata"]["priced"] == 2
    assert DC.evaluate(200, _body([0, 0, 0]))["status"] == "down"


def test_dra_error_inside_200_is_down_not_empty():
    r = DC.evaluate(200, {"_dra_error": True, "status_code": 504, "detail": "extract_prices cap"})
    assert r["status"] == "down" and "504" in r["error_message"]


def test_no_answer_http_error_missing_page():
    assert DC.evaluate(None, None, "ConnectError: refused")["status"] == "down"
    assert DC.evaluate(503, None)["status"] == "down"
    part = {"results": [{"url": DC.PAGES[0], "facts_count": 5}], "total_facts": 5}
    r = DC.evaluate(200, part)
    assert r["status"] == "degraded" and [p["outcome"] for p in r["metadata"]["pages"]][1:] == ["missing", "missing"]


def test_run_posts_the_same_call_as_mrs():
    seen = {}

    def post(url, payload, timeout):
        seen.update(url=url, payload=payload)
        return 200, _body([3, 4, 5])
    r = DC.run("https://dra.example", post=post)
    assert seen["url"] == "https://dra.example/api/extract_prices" and seen["payload"]["urls"] == DC.PAGES
    assert r["status"] == "healthy" and r["metadata"]["total_facts"] == 12
    assert DC.run(None)["status"] == "down"


def test_wake_sleeping_dra_before_the_check(monkeypatch):
    """[24.11 · ложная тревога 00:52 UTC] спящий Eco-DRA: первый /health — 503, затем 200 → проверка цен идёт и «healthy»;
    DRA не проснулся за бюджет → «down» с причиной «не проснулся», запрос цен не отправлен."""
    monkeypatch.setattr(DC.time, "sleep", lambda s: None)
    codes, asked = [503, 200], []
    r = DC.run("https://dra.example", post=lambda u, p, t: (asked.append(u), (200, _body([3, 4, 5])))[1],
               get=lambda u, t: codes.pop(0))
    assert r["status"] == "healthy" and r["metadata"]["wake"]["attempts"] == 2 and asked == ["https://dra.example/api/extract_prices"]
    asked.clear()
    clock = iter(range(0, 10_000, 3))                      # часы идут: каждый вызов +3 с (пауза подменена)
    monkeypatch.setattr(DC.time, "monotonic", lambda: next(clock))
    w = DC.wake("https://dra.example", get=lambda u, t: 503, budget_s=12, sleep=lambda s: None)
    assert w["ok"] is False and w["attempts"] >= 2 and w["last"] == 503
    monkeypatch.setattr(DC, "WAKE_BUDGET_S", 12)
    r2 = DC.run("https://dra.example", post=lambda u, p, t: (asked.append(u), (200, _body([3, 4, 5])))[1], get=lambda u, t: 503)
    assert r2["status"] == "down" and "не проснулся" in r2["error_message"] and asked == []


def test_base_url_from_monitored_services(monkeypatch):
    monkeypatch.delenv("DRA_CANARY_URL", raising=False)

    class C:
        MONITORED_SERVICES = [{"name": "Market Research", "url": "https://mrs"}, {"name": "Deep Research Agent", "url": "https://dra/"}]
    assert DC.dra_base_url(C()) == "https://dra"


def test_due_once_a_day_retry_after_6h():
    from monitoring.tasks import dra_canary_due
    now = datetime(2026, 11, 18, 12, 0)
    assert dra_canary_due(None, None, now)
    assert not dra_canary_due("healthy", now - timedelta(hours=3), now)
    assert dra_canary_due("healthy", now - timedelta(days=1), now)
    assert not dra_canary_due("down", now - timedelta(hours=2), now)
    assert dra_canary_due("down", now - timedelta(hours=7), now)


def test_task_writes_health_and_alerts_on_change(monkeypatch):
    from monitoring import tasks as T
    from monitoring.database import Base, engine, get_db_session
    from monitoring.models import ServiceHealth, SystemAlert
    Base.metadata.create_all(bind=engine)
    sent = []

    async def _send(self, alert):
        sent.append((alert.severity, alert.message))
    monkeypatch.setattr(T.AlertManager, "send_alert", _send)
    monkeypatch.setenv("DRA_CANARY_URL", "https://dra.example")
    ok = lambda u, p, t: (200, _body([10, 11, 10]))          # noqa: E731
    bad = lambda u, p, t: (200, _body([10, 0, 0]))           # noqa: E731
    assert T.dra_price_canary_task(post=ok)["status"] == "healthy"
    assert T.dra_price_canary_task(post=bad)["status"] == "skipped"          # уже проверено сегодня
    assert T.dra_price_canary_task(force=True, post=bad)["status"] == "degraded"
    assert T.dra_price_canary_task(force=True, post=ok)["status"] == "healthy"
    with get_db_session() as db:
        rows = [(r.status, (r.additional_info or {}).get("priced"))
                for r in db.query(ServiceHealth).filter(ServiceHealth.service_name == DC.SERVICE_NAME)
                .order_by(ServiceHealth.last_checked).all()]
        alerts = db.query(SystemAlert).filter(SystemAlert.service_name == DC.SERVICE_NAME).count()
    assert rows == [("healthy", 3), ("degraded", 1), ("healthy", 3)]
    # первая проверка «healthy» — без письма; ухудшение — warning; восстановление — info
    assert alerts == 2 and [s for s, _ in sent] == ["warning", "info"]


def test_scheduler_runs_the_canary():
    import inspect
    from monitoring import scheduler as S
    src = inspect.getsource(S.InProcessScheduler.start)
    assert "dra_price_canary_task" in src and '_run_periodic("dra_price_canary"' in src
