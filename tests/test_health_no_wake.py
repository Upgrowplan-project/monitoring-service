"""
[28.11 · владелец «2 да»] Heroku logs 25.11 14:25 – 27.11 21:52: user-service woke 12 times, 7 of them ~10 s after a monitoring
wake-up with GET / — the health check ran 5 s after EVERY monitoring start and woke its sleeping Eco neighbours (each wake-up
is ≥ 30 min of the shared Eco quota). Now: a service with "heroku_app" is checked through the Heroku Platform API (the request
goes to api.heroku.com and does not wake the dyno, checked live 28.11: two Eco apps stayed «idle»), an Eco dyno is never
requested by URL, a non-Eco (Basic) dyno is still checked by URL; the task runs only when the journal says it is due.
"""
import asyncio
from datetime import datetime, timedelta

import httpx
import pytest

from monitoring import health_checkers as hc
from monitoring import tasks


def _patch(monkeypatch, dynos, heroku_status=200, app_answer=200):
    """Heroku API answers `dynos`; every request to the service itself is recorded in `woke`."""
    woke, heroku = [], []
    real = httpx.AsyncClient

    def handler(request):
        if request.url.host == "api.heroku.com":
            heroku.append(request.url.path)
            return httpx.Response(heroku_status, json=dynos)
        woke.append(str(request.url))
        return httpx.Response(app_answer, json={"status": "ok"})

    monkeypatch.setattr(hc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return woke, heroku


def run():
    return asyncio.run(hc.HealthChecker.check_service_without_waking(
        "User Service", "https://user.example", "/", "upgrowplan-user-service", "key", up_on_any_response=True))


def dyno(state, size="Eco", type_="web"):
    return {"type": type_, "state": state, "size": size}


@pytest.mark.parametrize("state,sleeping", [("idle", True), ("up", False), ("starting", False)])
def test_eco_dyno_is_never_requested_by_url(monkeypatch, state, sleeping):
    woke, heroku = _patch(monkeypatch, [dyno(state)])
    r = run()
    assert r["status"] == "healthy" and woke == [] and heroku == ["/apps/upgrowplan-user-service/dynos"]
    assert r["metadata"]["sleeping"] is sleeping and r["metadata"]["checked_via"] == "heroku_api"


@pytest.mark.parametrize("state", ["crashed", "down"])
def test_crashed_dyno_is_down_without_waking(monkeypatch, state):
    woke, _ = _patch(monkeypatch, [dyno(state)])
    r = run()
    assert r["status"] == "down" and state in r["error_message"] and woke == []


def test_no_web_dynos_is_down(monkeypatch):
    woke, _ = _patch(monkeypatch, [dyno("up", type_="worker")])
    r = run()
    assert r["status"] == "down" and r["error_message"] == "no web dynos" and woke == []


def test_basic_dyno_is_still_checked_by_url(monkeypatch):
    woke, _ = _patch(monkeypatch, [dyno("up", size="Basic")])
    r = run()
    assert r["status"] == "healthy" and woke == ["https://user.example/"]
    assert r["metadata"]["dyno_sizes"] == ["Basic"]


def test_basic_dyno_answering_500_is_down(monkeypatch):
    woke, _ = _patch(monkeypatch, [dyno("up", size="Basic")], app_answer=500)
    assert run()["status"] == "down" and len(woke) == 1


@pytest.mark.parametrize("code", [401, 403, 500])
def test_heroku_api_failure_does_not_wake_the_service(monkeypatch, code):
    woke, _ = _patch(monkeypatch, [], heroku_status=code)
    r = run()
    assert r["status"] == "degraded" and f"HTTP {code}" in r["error_message"] and woke == []


class _Cfg:
    VERCEL_TOKEN = VERCEL_PROJECT_ID = OPENAI_API_KEY = None
    HEROKU_APP_NAMES = []
    APIFY_API_TOKEN = SERPER_API_KEY = GOOGLE_CSE_API_KEY = MARKET_RESEARCH_REDIS_URL = None
    OTHER_API_KEYS = {}
    DATABASE_URL = "sqlite://"

    def __init__(self, key, services):
        self.HEROKU_API_KEY = key
        self.MONITORED_SERVICES = services


SERVICES = [
    {"name": "User Service", "url": "https://user.example", "health_path": "/", "liveness": "any",
     "heroku_app": "upgrowplan-user-service"},
    {"name": "Synth Focus Lab", "url": "https://synth.example", "health_path": "/health"},
]


def test_check_all_services_uses_heroku_only_for_marked_services(monkeypatch):
    woke, heroku = _patch(monkeypatch, [dyno("idle")])
    results = asyncio.run(hc.check_all_services(_Cfg("key", SERVICES), wake_retry_delay=0))
    by = {r["service_name"]: r for r in results}
    assert by["User Service"]["status"] == "healthy" and heroku == ["/apps/upgrowplan-user-service/dynos"]
    assert woke == ["https://synth.example/health"]  # no heroku_app → old behaviour, by URL


def test_without_heroku_key_old_behaviour_is_unchanged(monkeypatch):
    woke, heroku = _patch(monkeypatch, [dyno("idle")])
    asyncio.run(hc.check_all_services(_Cfg(None, SERVICES), wake_retry_delay=0))
    assert heroku == [] and sorted(woke) == ["https://synth.example/health", "https://user.example/"]


def test_health_check_due_by_journal():
    now = datetime(2026, 11, 28, 12, 0)
    day = 86400
    assert tasks.health_check_due(None, now, day) is True
    assert tasks.health_check_due(now - timedelta(hours=1), now, day) is False   # monitoring woke again an hour later
    assert tasks.health_check_due(now - timedelta(hours=25), now, day) is True


def test_scheduler_ticks_at_most_hourly():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "monitoring" / "scheduler.py").read_text(encoding="utf-8")
    assert 'min(float(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "300")), 3600.0)' in src
