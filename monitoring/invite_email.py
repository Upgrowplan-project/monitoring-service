"""Localized HTML and plain-text copy for one-time sign-in links: beta/account invites and self-service login links.

[22.10 · owner «вид не очень», «вид ссылки настораживает», «добавить о безопасности»; tester's invite landed in Gmail
«Промоакции», mail-tester 8.5/10: HTML only, 14 % text] — a plain-text part, a short letter that says what the service is
and how to start, ONE button in HTML (no long token address on display — it is in the plain-text part only), a safety note
and how to sign in again on another device (the link is one-time).

`direct_link`: the button shows the real upgrowplan.com address (Resend, no click tracking). Through Brevo the button
passes its click-tracking host first — the safety note must not then claim «hover to see upgrowplan.com».
"""

from html import escape

REPLY_TO = {"name": "Upgrowplan", "email": "info@upgrowplan.com"}
SITE = "www.upgrowplan.com"


def invite_expiry_days(invite_url: str) -> int:
    """User service: beta link of an existing account (BetaInviteService) — 14 days; a new account (AdminUserController) — 7."""
    return 14 if "/market-research/accept" in (invite_url or "") else 7


def _safety(ru: bool, direct_link: bool) -> str:
    if ru:
        where = (f"кнопка ведёт на наш сайт {SITE} — это видно, если навести на неё курсор или удерживать её пальцем."
                 if direct_link else f"кнопка открывает наш сайт {SITE} (переход идёт через почтовый сервис Brevo).")
        return (f"О безопасности: {where} По ссылке мы никогда не просим пароль, данные карты или оплату. Ссылка открывает "
                "только ваш аккаунт и работает один раз. Если вы не ждали этого письма — просто удалите его.")
    where = (f"the button leads to our website {SITE} — you can see it by hovering over the button or pressing and holding it."
             if direct_link else f"the button opens our website {SITE} (the click passes through the Brevo mailing service).")
    return (f"About safety: {where} We never ask for a password, card details or payment through this link. The link opens "
            "only your account and works once. If you did not expect this email, just delete it.")


def _letter(paragraphs: list[str], button: str, url: str, after: list[str], signoff_html: str) -> str:
    body = "".join(paragraphs)
    body += (f'<p style="margin:24px 0"><a href="{escape(url, quote=True)}" style="background:#176b83;color:#ffffff;'
             f'padding:12px 22px;border-radius:6px;text-decoration:none;display:inline-block">{escape(button)}</a></p>')
    body += "".join(after)
    return ('<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.5;max-width:560px;color:#1f2937">'
            f"{body}{signoff_html}</div>")


def _small(text: str) -> str:
    return f'<p style="font-size:13px;color:#475569">{escape(text)}</p>'


def build_invite_email(invite_url: str, locale: str, beta: bool, direct_link: bool = True) -> dict[str, str]:
    """Invite with a one-time sign-in link. Returns subject, textContent, htmlContent."""
    ru = (locale or "").lower().startswith("ru")
    days = invite_expiry_days(invite_url)
    if ru:
        if beta:
            subject = "Приглашение в бета-тест Market Research — Upgrowplan"
            intro = ["Здравствуйте!",
                     "Вас пригласили в бета-тест Upgrowplan Market Research — сервиса, который за 15–40 минут готовит "
                     "маркетинговое исследование вашей идеи: конкуренты и их цены, средний чек, объём рынка и вывод о запуске. "
                     "У каждой цифры — источник или пометка «допущение».",
                     "Для вас открыто 2 запуска исследования."]
            steps = ["Нажмите кнопку на том компьютере и в том браузере, где будете работать: ссылка одноразовая.",
                     "Опишите продукт и запустите исследование. В бета-версии лучше всего работают цифровые продукты — "
                     "SaaS, приложения, платформы.",
                     "Когда отчёт будет готов, оцените его прямо на странице — это главная помощь нам."]
            button = "Начать бета-тест"
        else:
            subject = "Ваш аккаунт Upgrowplan готов"
            intro = ["Здравствуйте!", "Для вас создан аккаунт Upgrowplan."]
            steps = ["Нажмите кнопку на том компьютере и в том браузере, где будете работать: ссылка одноразовая.",
                     "После входа почта будет подтверждена, а аккаунт — готов к работе."]
            button = "Войти в Upgrowplan"
        steps_title = "Как начать:"
        expiry = f"Ссылка действует {days} дней."
        broken = "Если кнопка не открывается — ответьте на это письмо, и мы пришлём ссылку по-другому."
        copy_text = "Если кнопка не открывается, скопируйте адрес в браузер:"
        again = ("Чтобы войти позже или с другого устройства: upgrowplan.com → «Войти» → «Получить ссылку для входа» — "
                 "мы пришлём новую ссылку на эту почту.")
        reply = "Вопросы и замечания — просто ответьте на это письмо."
        signoff_text, signoff_html = "С уважением,\nкоманда Upgrowplan\nupgrowplan.com", \
            '<p style="color:#64748b">С уважением,<br>команда Upgrowplan · upgrowplan.com</p>'
    else:
        if beta:
            subject = "Your invitation to the Market Research beta — Upgrowplan"
            intro = ["Hello,",
                     "You are invited to the beta test of Upgrowplan Market Research — a service that prepares a market "
                     "study of your idea in 15–40 minutes: competitors and their prices, average check, market size and a "
                     "launch verdict. Every number has a source or is marked as an assumption.",
                     "You have 2 research runs."]
            steps = ["Press the button on the computer and in the browser you will work in: the link is one-time.",
                     "Describe your product and start a study. In the beta, digital products work best — SaaS, apps, "
                     "platforms.",
                     "When the report is ready, rate it right on the page — that helps us most."]
            button = "Start the beta test"
        else:
            subject = "Your Upgrowplan account is ready"
            intro = ["Hello,", "An Upgrowplan account has been created for you."]
            steps = ["Press the button on the computer and in the browser you will work in: the link is one-time.",
                     "Signing in confirms your email and the account is ready to use."]
            button = "Sign in to Upgrowplan"
        steps_title = "How to start:"
        expiry = f"The link is valid for {days} days."
        broken = "If the button does not open, reply to this email and we will send the link another way."
        copy_text = "If the button does not open, copy this address into your browser:"
        again = ("To sign in later or on another device: upgrowplan.com → “Sign in” → “Email me a sign-in link” — we "
                 "will send a new link to this address.")
        reply = "Questions or comments — just reply to this email."
        signoff_text, signoff_html = "Best regards,\nthe Upgrowplan team\nupgrowplan.com", \
            '<p style="color:#64748b">Best regards,<br>the Upgrowplan team · upgrowplan.com</p>'

    safety = _safety(ru, direct_link)
    text = "\n\n".join(intro) + f"\n\n{steps_title}\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    text += (f"\n\n{button}: {invite_url}\n\n{expiry} {copy_text}\n{invite_url}\n\n{safety}\n\n{again}\n\n{reply}"
             f"\n\n{signoff_text}")
    html = _letter(
        [f"<p>{escape(p)}</p>" for p in intro]
        + [f'<p style="margin-bottom:4px">{escape(steps_title)}</p><ol style="margin-top:0">'
           + "".join(f"<li>{escape(s)}</li>" for s in steps) + "</ol>"],
        button, invite_url,
        [_small(f"{expiry} {broken}"), _small(safety), f"<p>{escape(again)}</p>", f"<p>{escape(reply)}</p>"],
        signoff_html,
    )
    return {"subject": subject, "textContent": text, "htmlContent": html}


def build_login_link_email(login_url: str, locale: str, minutes: int, direct_link: bool = True) -> dict[str, str]:
    """Self-service sign-in link (no password). Returns subject, textContent, htmlContent."""
    ru = (locale or "").lower().startswith("ru")
    if ru:
        subject = "Ссылка для входа в Upgrowplan"
        intro = ["Здравствуйте!", "Вы запросили ссылку для входа в Upgrowplan."]
        button = "Войти в Upgrowplan"
        expiry = (f"Ссылка действует {minutes} минут. Нажмите кнопку в том браузере, где будете работать.")
        broken = "Если кнопка не открывается — запросите ссылку ещё раз или ответьте на это письмо."
        copy_text = "Если кнопка не открывается, скопируйте адрес в браузер:"
        signoff_text, signoff_html = "С уважением,\nкоманда Upgrowplan\nupgrowplan.com", \
            '<p style="color:#64748b">С уважением,<br>команда Upgrowplan · upgrowplan.com</p>'
    else:
        subject = "Your Upgrowplan sign-in link"
        intro = ["Hello,", "You asked for a link to sign in to Upgrowplan."]
        button = "Sign in to Upgrowplan"
        expiry = f"The link is valid for {minutes} minutes. Press the button in the browser you will work in."
        broken = "If the button does not open, request a new link or reply to this email."
        copy_text = "If the button does not open, copy this address into your browser:"
        signoff_text, signoff_html = "Best regards,\nthe Upgrowplan team\nupgrowplan.com", \
            '<p style="color:#64748b">Best regards,<br>the Upgrowplan team · upgrowplan.com</p>'
    safety = _safety(ru, direct_link)
    text = "\n\n".join(intro) + f"\n\n{button}: {login_url}\n\n{expiry} {copy_text}\n{login_url}\n\n{safety}\n\n{signoff_text}"
    html = _letter([f"<p>{escape(p)}</p>" for p in intro], button, login_url,
                   [_small(f"{expiry} {broken}"), _small(safety)], signoff_html)
    return {"subject": subject, "textContent": text, "htmlContent": html}
