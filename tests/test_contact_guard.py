"""P1 (audit 2026-09): public contact form guard + /reports/debug no longer public."""
import importlib
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
cg = importlib.import_module("monitoring.contact_guard")
auth = importlib.import_module("monitoring.auth")


def test_valid_contact_normalizes():
    c = cg.ContactIn(name="  Ann ", email=" Ann@Example.COM ", message="hi")
    assert c.name == "Ann" and c.email == "ann@example.com"


@pytest.mark.parametrize("email", ["", "x", "a@b", "a b@c.io", "a@b.c", "<x>@y.io", "a@b.io\r\nBcc: z@q.io", "a" * 260 + "@x.io"])
def test_bad_email_rejected(email):
    with pytest.raises(ValidationError):
        cg.ContactIn(email=email, message="hi")


def test_name_with_newline_rejected_and_long_message_rejected():
    with pytest.raises(ValidationError):
        cg.ContactIn(name="a\r\nX-Injected: 1", email="a@b.io", message="hi")
    with pytest.raises(ValidationError):
        cg.ContactIn(email="a@b.io", message="x" * 4001)
    with pytest.raises(ValidationError):
        cg.ContactIn(email="a@b.io", message="   ")


def test_html_name_is_escaped():
    assert cg.html_escape_name('<img src=x onerror=alert(1)>') == "&lt;img src=x onerror=alert(1)&gt;"
    assert cg.html_escape_name(None) == ""


def test_limiter_three_per_hour_per_ip():
    lim = cg.ContactLimiter(max_calls=3, window_seconds=3600)
    t = 100.0
    assert all(lim.allow("1.1.1.1", t + i) for i in range(3))
    assert lim.allow("1.1.1.1", t + 3) is False
    assert lim.allow("2.2.2.2", t + 3) is True
    assert lim.allow("1.1.1.1", t + 3601) is True


def test_reports_debug_requires_admin(monkeypatch):
    monkeypatch.delenv("MONITORING_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("JWT_SECRET", "s" * 64)
    assert ("GET", "/api/monitoring/reports/debug") not in auth.PUBLIC_ENDPOINTS
    assert auth.check_request("GET", "/api/monitoring/reports/debug", None, None) == (401, "Missing admin token")
    # contact stays public
    assert auth.check_request("POST", "/api/monitoring/contact", None, None) is None
