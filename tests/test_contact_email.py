"""Localized contact-form auto-reply content."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
email_copy = importlib.import_module("monitoring.contact_email")


@pytest.mark.parametrize("referer,expected", [
    ("https://www.upgrowplan.com/ru/contacts", "ru"),
    ("https://www.upgrowplan.com/ru", "ru"),
    ("https://www.upgrowplan.com/contacts", "en"),
    (None, "en"),
])
def test_legacy_contact_locale_comes_from_referer_path(referer, expected):
    assert email_copy.resolve_contact_locale(None, referer) == expected


def test_explicit_contact_locale_takes_precedence_over_referer():
    assert email_copy.resolve_contact_locale("en", "https://www.upgrowplan.com/ru/contacts") == "en"


@pytest.mark.parametrize("locale,expected,forbidden", [
    ("en", "Thank you for signing up", "Спасибо"),
    ("ru", "Спасибо за заявку", "Thank you for signing up"),
])
def test_beta_auto_reply_uses_only_requested_language(locale, expected, forbidden):
    result = email_copy.build_contact_auto_reply(locale, "Denis", is_beta=True)

    assert expected in result["textContent"]
    assert forbidden not in result["textContent"]
    assert forbidden not in result["htmlContent"]
    assert "https://www.linkedin.com/company/upgrowplan" in result["textContent"]
    assert 'href="https://www.linkedin.com/company/upgrowplan"' in result["htmlContent"]
    assert "<img" not in result["htmlContent"]


def test_name_is_escaped_in_html_auto_reply():
    result = email_copy.build_contact_auto_reply("en", '<img src=x onerror="alert(1)">', is_beta=False)

    assert "&lt;img" in result["htmlContent"]
    assert "<img" not in result["htmlContent"]
