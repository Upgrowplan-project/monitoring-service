"""One-time sign-in link emails (beta/account invite, login link): text part, honest copy, no URL-looking link text.

[22.10] tester's invite went to Gmail «Промоакции»; mail-tester 8.5/10 (MIME_HTML_ONLY, 14 % text) and the visible URL
under the button pointed to Brevo's click-tracking host — the copy-paste address must be plain text, not a link.
"""

import importlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
invite = importlib.import_module("monitoring.invite_email")

NEW_ACCOUNT_URL = "https://www.upgrowplan.com/ru/beta/accept?token=" + "a" * 64
BETA_URL = "https://www.upgrowplan.com/en/beta/market-research/accept?token=" + "b" * 64
LOGIN_URL = "https://www.upgrowplan.com/ru/auth/link?token=" + "c" * 64


def _anchor_texts(html: str) -> list[str]:
    return re.findall(r"<a\b[^>]*>(.*?)</a>", html, flags=re.S)


@pytest.mark.parametrize("url,locale,beta", [
    (NEW_ACCOUNT_URL, "ru", True), (BETA_URL, "en", True), (NEW_ACCOUNT_URL, "ru", False), (BETA_URL, "en", False),
])
def test_invite_html_is_one_button_without_the_long_address(url, locale, beta):
    """[22.10 · owner] «вид ссылки настораживает» → HTML shows only the button; the address stays in the text part."""
    letter = invite.build_invite_email(url, locale, beta)
    assert set(letter) == {"subject", "textContent", "htmlContent"}
    assert url in letter["textContent"]
    html = letter["htmlContent"]
    assert html.count(f'href="{url}"') == 1                       # one link: the button
    assert html.count(url) == 1                                   # nowhere else in HTML
    assert all("http" not in t for t in _anchor_texts(html))
    assert "<img" not in html


@pytest.mark.parametrize("locale,expected,forbidden", [
    ("ru", ["одноразовая", "Получить ссылку для входа", "ответьте на это письмо", "2 запуска", "О безопасности",
            "никогда не просим пароль"], "Hello"),
    ("en", ["one-time", "Email me a sign-in link", "reply to this email", "2 research runs", "About safety",
            "never ask for a password"], "Здравствуйте"),
])
def test_invite_copy_language_and_content(locale, expected, forbidden):
    letter = invite.build_invite_email(NEW_ACCOUNT_URL, locale, True)
    for part in ("textContent", "htmlContent"):
        for phrase in expected:
            assert phrase in letter[part], (part, phrase)
        assert forbidden not in letter[part]


@pytest.mark.parametrize("builder", [
    lambda d: invite.build_invite_email(NEW_ACCOUNT_URL, "ru", True, d),
    lambda d: invite.build_login_link_email(LOGIN_URL, "ru", 30, d),
])
def test_safety_note_claims_hover_address_only_when_the_link_is_direct(builder):
    """Through Brevo the button goes via its tracking host — «видно, если навести» would be false there."""
    assert "навести на неё курсор" in builder(True)["htmlContent"]
    brevo = builder(False)["htmlContent"]
    assert "навести" not in brevo and "через почтовый сервис Brevo" in brevo


def test_expiry_days_follow_the_link_kind():
    assert "14 days" in invite.build_invite_email(BETA_URL, "en", True)["textContent"]
    assert "7 дней" in invite.build_invite_email(NEW_ACCOUNT_URL, "ru", True)["textContent"]


def test_url_is_escaped_in_html():
    url = 'https://www.upgrowplan.com/ru/beta/accept?token=x&y="<b>'
    html = invite.build_invite_email(url, "ru", True)["htmlContent"]
    assert "<b>" not in html and "&amp;y=" in html


@pytest.mark.parametrize("locale,phrase", [("ru", "30 минут"), ("en", "30 minutes")])
def test_login_link_email(locale, phrase):
    letter = invite.build_login_link_email(LOGIN_URL, locale, 30)
    assert phrase in letter["textContent"] and LOGIN_URL in letter["textContent"]
    html = letter["htmlContent"]
    assert html.count(f'href="{LOGIN_URL}"') == 1
    assert all("http" not in t for t in _anchor_texts(html))


mailer = importlib.import_module("monitoring.link_mailer")


def _cfg(resend="", brevo="k", token=""):
    return SimpleNamespace(RESEND_API_KEY=resend, BREVO_API_KEY=brevo, SMTP_FROM_EMAIL="info@upgrowplan.com",
                           USER_SERVICE_MAIL_TOKEN=token)


def _capture(monkeypatch, cfg, resend_fails=False):
    sent = {"resend": [], "brevo": []}
    monkeypatch.setattr(mailer, "get_config", lambda: cfg)

    def resend(key, payload):
        if resend_fails:
            raise RuntimeError("422 domain not verified")
        sent["resend"].append(payload)

    monkeypatch.setattr(mailer, "send_resend_email", resend)
    monkeypatch.setattr(mailer, "send_brevo_email", lambda key, payload: sent["brevo"].append(payload))
    return sent


def test_invite_goes_through_resend_with_text_part_reply_to_and_direct_link(monkeypatch):
    main = importlib.import_module("main")
    sent = _capture(monkeypatch, _cfg(resend="re_x"))
    assert main._send_beta_or_account_invite("t@example.com", NEW_ACCOUNT_URL, "ru", "BETA_TESTER", True) == "resend"
    p = sent["resend"][0]
    assert not sent["brevo"]
    assert p["to"] == ["t@example.com"] and p["from"] == "Upgrowplan <info@upgrowplan.com>"
    assert p["reply_to"] == "info@upgrowplan.com" and p["text"] and p["subject"]
    assert "навести на неё курсор" in p["html"]


def test_without_resend_key_invite_goes_through_brevo_with_honest_note(monkeypatch):
    main = importlib.import_module("main")
    sent = _capture(monkeypatch, _cfg())
    assert main._send_beta_or_account_invite("t@example.com", NEW_ACCOUNT_URL, "ru", "BETA_TESTER", True) == "brevo"
    p = sent["brevo"][0]
    assert p["textContent"] and p["replyTo"]["email"] == "info@upgrowplan.com" and p["tags"] == ["beta-invite"]
    assert "через почтовый сервис Brevo" in p["htmlContent"]


def test_resend_refusal_falls_back_to_brevo_and_says_so(monkeypatch):
    main = importlib.import_module("main")
    sent = _capture(monkeypatch, _cfg(resend="re_x"), resend_fails=True)
    assert main._send_beta_or_account_invite("t@example.com", NEW_ACCOUNT_URL, "en", "USER", False) == "brevo-fallback"
    assert sent["brevo"] and "Brevo mailing service" in sent["brevo"][0]["htmlContent"]


def test_nothing_configured_reports_not_sent(monkeypatch):
    main = importlib.import_module("main")
    _capture(monkeypatch, _cfg(brevo=""))
    assert main._send_beta_or_account_invite("t@example.com", NEW_ACCOUNT_URL, "ru", "BETA_TESTER", True) == ""


def _client(monkeypatch, token):
    from fastapi.testclient import TestClient
    main = importlib.import_module("main")
    monkeypatch.setattr(main, "get_config", lambda: _cfg(resend="re_x", token=token))
    return TestClient(main.app)


def test_login_link_endpoint_fails_closed_without_token(monkeypatch):
    sent = _capture(monkeypatch, _cfg(resend="re_x"))
    r = _client(monkeypatch, "").post("/api/internal/login-link-email", json={"email": "a@b.io", "url": LOGIN_URL})
    assert r.status_code == 503 and not sent["resend"]


def test_login_link_endpoint_requires_the_shared_token(monkeypatch):
    sent = _capture(monkeypatch, _cfg(resend="re_x"))
    r = _client(monkeypatch, "s3cret").post("/api/internal/login-link-email", json={"email": "a@b.io", "url": LOGIN_URL},
                                           headers={"X-Internal-Token": "wrong"})
    assert r.status_code == 403 and not sent["resend"]


def test_login_link_endpoint_sends_only_links_to_our_site(monkeypatch):
    sent = _capture(monkeypatch, _cfg(resend="re_x"))
    c = _client(monkeypatch, "s3cret")
    h = {"X-Internal-Token": "s3cret"}
    bad = c.post("/api/internal/login-link-email", json={"email": "a@b.io", "url": "https://evil.example/x"}, headers=h)
    assert bad.status_code == 400 and not sent["resend"]
    ok = c.post("/api/internal/login-link-email", json={"email": "a@b.io", "url": LOGIN_URL, "locale": "ru", "minutes": 30},
                headers=h)
    assert ok.status_code == 200 and ok.json()["emailVia"] == "resend"
    assert sent["resend"][0]["subject"] == "Ссылка для входа в Upgrowplan" and "30 минут" in sent["resend"][0]["text"]
