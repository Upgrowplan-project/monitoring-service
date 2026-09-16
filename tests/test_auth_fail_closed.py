"""
P0 security gate (audit 2026-09): monitoring auth must be fail-CLOSED.
Runs without DB: tests monitoring.auth.check_request / verify_ws_token directly.
"""
import datetime as dt
import importlib
import sys
from pathlib import Path

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
auth = importlib.import_module("monitoring.auth")

SECRET = "s" * 64


def _admin_jwt(role="ADMIN", secret=SECRET, exp_delta=3600):
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": "admin@x", "role": role, "iat": now, "exp": now + dt.timedelta(seconds=exp_delta)},
        secret, algorithm="HS512",
    )


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("JWT_SECRET", "MONITORING_INGEST_TOKEN", "MONITORING_AUTH_DISABLED"):
        monkeypatch.delenv(k, raising=False)


# ── fail-closed: секреты НЕ заданы ─────────────────────────────────────────
def test_no_secret_guarded_read_is_503_not_open():
    assert auth.check_request("GET", "/api/monitoring/emails", None, None) == (503, "Auth not configured")


def test_no_secret_valid_looking_token_still_denied():
    tok = _admin_jwt(secret="other-secret" * 8)
    assert auth.check_request("GET", "/api/monitoring/emails", f"Bearer {tok}", None)[0] == 503


def test_no_ingest_token_env_ingest_is_503():
    assert auth.check_request("POST", "/api/monitoring/reports", None, "anything") == (503, "Ingest token not configured")


def test_no_secret_websocket_denied():
    assert auth.verify_ws_token(_admin_jwt()) is False
    assert auth.verify_ws_token(None) is False


# ── public endpoints остаются публичными ───────────────────────────────────
def test_public_endpoints_stay_open_without_secret():
    assert auth.check_request("POST", "/api/monitoring/pageview", None, None) is None
    assert auth.check_request("POST", "/api/monitoring/contact", None, None) is None
    assert auth.check_request("OPTIONS", "/api/monitoring/emails", None, None) is None
    assert auth.check_request("GET", "/health", None, None) is None  # вне guarded prefixes


# ── explicit dev switch ────────────────────────────────────────────────────
def test_explicit_disable_flag_opens(monkeypatch):
    monkeypatch.setenv("MONITORING_AUTH_DISABLED", "1")
    assert auth.check_request("GET", "/api/monitoring/emails", None, None) is None
    assert auth.verify_ws_token(None) is True


# ── configured: нормальная работа ──────────────────────────────────────────
def test_configured_admin_ok_user_forbidden_missing_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    assert auth.check_request("GET", "/api/monitoring/emails", f"Bearer {_admin_jwt()}", None) is None
    assert auth.check_request("GET", "/api/monitoring/emails", f"Bearer {_admin_jwt(role='USER')}", None) == (403, "Admin access required")
    assert auth.check_request("GET", "/api/monitoring/emails", None, None) == (401, "Missing admin token")
    assert auth.check_request("GET", "/api/monitoring/emails", f"Bearer {_admin_jwt(exp_delta=-10)}", None) == (401, "Token expired")
    assert auth.verify_ws_token(_admin_jwt()) is True


def test_configured_ingest_token_compare(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("MONITORING_INGEST_TOKEN", "ingest-secret")
    assert auth.check_request("POST", "/api/monitoring/reports", None, "ingest-secret") is None
    assert auth.check_request("POST", "/api/monitoring/reports", None, "ingest-secreT") == (401, "Invalid ingest token")
    assert auth.check_request("POST", "/api/monitoring/reports", None, None) == (401, "Invalid ingest token")
