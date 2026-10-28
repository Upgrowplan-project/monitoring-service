"""
[28.10 · owner «4»] A sleeping Heroku eco dyno answers 503 (router H99) while it wakes; on 24.10 that raised
«CRITICAL: Deep Research Agent — Service is down: HTTP 503» four times for an agent that answered 200 a moment later.
A «down» check is repeated once after a pause; only a second «down» is reported. The manual check-now endpoint keeps
one attempt (it runs inside an HTTP request Heroku cuts at 30 s). One web process = one in-process scheduler.
"""
import asyncio
from pathlib import Path

import httpx
import pytest

from monitoring import health_checkers as hc


def _patch(monkeypatch, answers):
    """answers: list of status codes or exceptions, consumed one per request."""
    calls = []
    real = httpx.AsyncClient

    def handler(request):
        calls.append(request.url.path)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return httpx.Response(a, json={"status": "ok"})

    monkeypatch.setattr(hc.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls


def run(**kw):
    return asyncio.run(hc.HealthChecker.check_http_service("Deep Research Agent", "https://dra.example", **kw))


@pytest.mark.parametrize("first", [503, 502, httpx.ConnectError("refused"), httpx.ReadTimeout("held")])
def test_waking_service_is_healthy_after_retry(monkeypatch, first):
    calls = _patch(monkeypatch, [first, 200])
    r = run(wake_retry_delay=0.01)
    assert r["status"] == "healthy" and len(calls) == 2
    assert r["metadata"]["first_attempt"]


def test_still_down_after_retry_is_reported(monkeypatch):
    calls = _patch(monkeypatch, [503, 503])
    r = run(wake_retry_delay=0.01)
    assert r["status"] == "down" and r["error_message"] == "HTTP 503" and len(calls) == 2


def test_no_retry_when_disabled(monkeypatch):
    calls = _patch(monkeypatch, [503, 200])
    r = run(wake_retry_delay=0)
    assert r["status"] == "down" and len(calls) == 1


@pytest.mark.parametrize("code,status", [(200, "healthy"), (404, "degraded")])
def test_non_down_answers_are_not_retried(monkeypatch, code, status):
    calls = _patch(monkeypatch, [code, 200])
    assert run(wake_retry_delay=0.01)["status"] == status and len(calls) == 1


def test_check_now_endpoint_keeps_one_attempt():
    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "check_all_services(config, wake_retry_delay=0)" in src


def test_single_web_process_runs_one_scheduler():
    # two uvicorn workers (Heroku default WEB_CONCURRENCY=2) each started the scheduler: every check, email and alert ran twice
    procfile = (Path(__file__).resolve().parents[1] / "Procfile").read_text(encoding="utf-8")
    assert "--workers 1" in procfile
