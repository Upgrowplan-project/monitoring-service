"""Narrow HTTP client for transactional email sent through Brevo."""

import httpx

from monitoring import get_config


BREVO_EMAIL_API_URL = "https://api.brevo.com/v3/smtp/email"


def send_brevo_email(api_key: str, payload: dict, timeout: float = 15.0) -> httpx.Response:
    """Send one Brevo email, routing only this API call through Fixie when configured."""
    config = get_config()
    fixie_url = (config.FIXIE_URL or "").strip()
    request_options = {"proxies": fixie_url} if fixie_url else {}

    response = httpx.post(
        BREVO_EMAIL_API_URL,
        headers={"api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
        **request_options,
    )
    response.raise_for_status()
    return response
