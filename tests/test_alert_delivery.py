"""[20.11] AlertManager.send_alert писал «Alert sent successfully» при отказе SMTP (535 Authentication Failed, локальный
прогон 20.11) — журнал зелёный при недоставке. Теперь итог по каналам; Telegram — для critical и warning
(«пора пополнить поставщика» = warning)."""
import asyncio
import logging
from datetime import datetime

from monitoring.alerting import AlertManager
from monitoring.models import SystemAlert


class Cfg:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ADMIN_EMAIL = "smtp.x", 587, "u", "p", "a@x"
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = None, None


def _alert(sev):
    return SystemAlert(severity=sev, service_name="Provider Tavily", message="low", created_at=datetime.utcnow())


def test_smtp_failure_is_not_delivered(monkeypatch, caplog):
    import smtplib

    class Boom:
        def __init__(self, *a, **k):
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication Failed")
    monkeypatch.setattr(smtplib, "SMTP", Boom)
    am = AlertManager()
    am.config = Cfg
    with caplog.at_level(logging.INFO):
        res = asyncio.run(am.send_alert(_alert("warning")))
    assert res == {"email": False}
    assert "NOT delivered" in caplog.text and "Alert delivered" not in caplog.text


def test_warning_goes_to_telegram(monkeypatch):
    am = AlertManager()
    am.config = type("C", (Cfg,), {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
    calls = []

    async def email(alert):
        return False

    async def tg(alert):
        calls.append(alert.severity)
        return True
    monkeypatch.setattr(am, "_send_email", email)
    monkeypatch.setattr(am, "_send_telegram", tg)
    assert asyncio.run(am.send_alert(_alert("warning"))) == {"email": False, "telegram": True}
    asyncio.run(am.send_alert(_alert("info")))
    assert calls == ["warning"]                     # info — без Telegram
