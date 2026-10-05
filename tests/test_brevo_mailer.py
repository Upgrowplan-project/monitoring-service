"""Brevo transactional email routing stays isolated to the Brevo HTTP client."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mailer = importlib.import_module("monitoring.brevo_mailer")


def test_brevo_email_uses_fixie_proxy_when_configured(monkeypatch):
    proxy_url = "http://fixie:token@proxy.example:80"
    monkeypatch.setattr(mailer, "get_config", lambda: SimpleNamespace(FIXIE_URL=proxy_url))
    response = Mock()
    monkeypatch.setattr(mailer.httpx, "post", Mock(return_value=response))

    result = mailer.send_brevo_email("test-key", {"to": [{"email": "person@example.com"}]})

    assert result is response
    response.raise_for_status.assert_called_once_with()
    mailer.httpx.post.assert_called_once_with(
        mailer.BREVO_EMAIL_API_URL,
        headers={"api-key": "test-key", "Content-Type": "application/json"},
        json={"to": [{"email": "person@example.com"}]},
        timeout=15.0,
        proxies=proxy_url,
    )


def test_brevo_email_keeps_direct_local_behavior_without_fixie(monkeypatch):
    monkeypatch.setattr(mailer, "get_config", lambda: SimpleNamespace(FIXIE_URL=None))
    response = Mock()
    monkeypatch.setattr(mailer.httpx, "post", Mock(return_value=response))

    mailer.send_brevo_email("test-key", {"to": [{"email": "person@example.com"}]})

    assert "proxies" not in mailer.httpx.post.call_args.kwargs
    response.raise_for_status.assert_called_once_with()
