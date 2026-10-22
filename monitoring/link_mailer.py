"""Delivery of one-time sign-in link emails (invites, login links).

[22.10] Brevo rewrites every HTML link to its click-tracking host (sendibt3.com) and cannot switch it off on our plan;
the tester saw a foreign address on hover and the invite landed in Gmail «Промоакции». Resend sends with tracking off by
default, so these letters go there; Brevo stays as the path when Resend is not configured or refuses — the letter then
says honestly that the button passes through the mailing service, and the caller learns which path was taken.
"""

import logging
from typing import Callable

import httpx

from monitoring import get_config
from monitoring.brevo_mailer import send_brevo_email
from monitoring.invite_email import REPLY_TO

logger = logging.getLogger(__name__)

RESEND_EMAIL_API_URL = "https://api.resend.com/emails"
SENDER_NAME = "Upgrowplan"


def send_resend_email(api_key: str, payload: dict, timeout: float = 15.0) -> httpx.Response:
    response = httpx.post(RESEND_EMAIL_API_URL, headers={"Authorization": f"Bearer {api_key}"}, json=payload, timeout=timeout)
    response.raise_for_status()
    return response


def send_link_email(to: str, build: Callable[[bool], dict], tag: str) -> str:
    """Send a one-time link letter. `build(direct_link)` returns subject/textContent/htmlContent; `direct_link` is True when
    the button will show the real address (Resend). Returns "resend", "brevo", "brevo-fallback" or "" (not sent)."""
    cfg = get_config()
    sender = cfg.SMTP_FROM_EMAIL or "info@upgrowplan.com"
    resend_key = (cfg.RESEND_API_KEY or "").strip()
    if resend_key:
        letter = build(True)
        try:
            send_resend_email(resend_key, {
                "from": f"{SENDER_NAME} <{sender}>", "to": [to], "reply_to": REPLY_TO["email"],
                "subject": letter["subject"], "html": letter["htmlContent"], "text": letter["textContent"],
                "tags": [{"name": "kind", "value": tag.replace("-", "_")}],
            })
            return "resend"
        except Exception as exc:
            logger.warning("[LINK-MAIL] Resend refused %s (%s) → Brevo: %s", to, tag, exc)
    brevo_key = (cfg.BREVO_API_KEY or "").strip()
    if not brevo_key:
        return ""
    letter = build(False)
    try:
        send_brevo_email(brevo_key, {
            "sender": {"name": SENDER_NAME, "email": sender}, "replyTo": REPLY_TO, "to": [{"email": to}],
            "tags": [tag], **letter,
        })
        return "brevo-fallback" if resend_key else "brevo"
    except Exception as exc:
        logger.warning("[LINK-MAIL] Brevo refused %s (%s): %s", to, tag, exc)
        return ""
