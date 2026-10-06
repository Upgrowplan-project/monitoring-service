"""Localized HTML and plain-text copy for public contact-form auto-replies."""

from urllib.parse import urlsplit

from monitoring.contact_guard import html_escape_name


LINKEDIN_URL = "https://www.linkedin.com/company/upgrowplan"


def resolve_contact_locale(locale: str | None, referer: str | None = None) -> str:
    if locale in {"en", "ru"}:
        return locale
    path = urlsplit(referer or "").path.rstrip("/")
    return "ru" if path == "/ru" or path.startswith("/ru/") else "en"


def build_contact_auto_reply(locale: str, name: str | None, is_beta: bool) -> dict[str, str]:
    locale = resolve_contact_locale(locale)
    safe_name = html_escape_name(name)

    if locale == "ru":
        subject = "Спасибо за ваш интерес к Upgrowplan!"
        greeting_text = f"Здравствуйте, {name}!\n\n" if name else "Здравствуйте!\n\n"
        greeting_html = f"<p>Здравствуйте, <strong>{safe_name}</strong>!</p>" if name else "<p>Здравствуйте!</p>"
        if is_beta:
            message_text = (
                "Спасибо за заявку на бета-тестирование! Мы добавили вас в список раннего доступа. "
                "Свяжемся с вами, когда откроется место.\n\n"
            )
            message_html = (
                "<p>Спасибо за заявку на бета-тестирование! Мы добавили вас в список раннего доступа. "
                "Свяжемся с вами, когда откроется место.</p>"
            )
        else:
            message_text = "Мы получили ваше сообщение и скоро ответим. Спасибо, что написали нам!\n\n"
            message_html = "<p>Мы получили ваше сообщение и скоро ответим. Спасибо, что написали нам!</p>"
        follow_text = f"Следите за обновлениями Upgrowplan в LinkedIn: {LINKEDIN_URL}"
        follow_html = (
            f'<p>Следите за обновлениями Upgrowplan в '
            f'<a href="{LINKEDIN_URL}" style="color:#1e6078;">LinkedIn</a>.</p>'
        )
        signoff_text = "С уважением,\nКоманда Upgrowplan\nupgrowplan.com"
        signoff_html = '<p style="color:#64748b;">С уважением,<br>Команда Upgrowplan · upgrowplan.com</p>'
    else:
        subject = "Thank you for your interest in Upgrowplan!"
        greeting_text = f"Hi {name},\n\n" if name else "Hi,\n\n"
        greeting_html = f"<p>Hi <strong>{safe_name}</strong>,</p>" if name else "<p>Hi,</p>"
        if is_beta:
            message_text = (
                "Thank you for signing up! We've added you to our early access list. "
                "We'll reach out as soon as your spot opens up.\n\n"
            )
            message_html = (
                "<p>Thank you for signing up! We've added you to our <strong>early access list</strong>. "
                "We'll reach out as soon as your spot opens up.</p>"
            )
        else:
            message_text = "We've received your message and will get back to you soon. Thanks for reaching out!\n\n"
            message_html = "<p>We've received your message and will get back to you soon. Thanks for reaching out!</p>"
        follow_text = f"Follow Upgrowplan on LinkedIn for service updates: {LINKEDIN_URL}"
        follow_html = (
            f'<p>Follow Upgrowplan on '
            f'<a href="{LINKEDIN_URL}" style="color:#1e6078;">LinkedIn</a> for service updates.</p>'
        )
        signoff_text = "Best regards,\nThe Upgrowplan Team\nupgrowplan.com"
        signoff_html = '<p style="color:#64748b;">Best regards,<br>The Upgrowplan Team · upgrowplan.com</p>'

    plain_text = f"{greeting_text}{message_text}{follow_text}\n\n{signoff_text}"
    html_content = (
        "<html><body style='font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'>"
        "<div style='background:#1e6078;padding:20px;border-radius:8px 8px 0 0;'>"
        "<h2 style='color:#fff;margin:0;'>Upgrowplan</h2></div>"
        "<div style='background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0;color:#1f2937;'>"
        f"{greeting_html}{message_html}{follow_html}"
        "<div style='color:#94a3b8;font-size:12px;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:12px;'>"
        f"{signoff_html}</div></div></body></html>"
    )
    return {"subject": subject, "textContent": plain_text, "htmlContent": html_content}
