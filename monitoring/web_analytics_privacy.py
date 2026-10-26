"""Privacy-safe URL normalization for anonymous web analytics events."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "authorization",
    "bearer",
    "code",
    "credential",
    "email",
    "id_token",
    "invite_token",
    "jwt",
    "key",
    "password",
    "refresh_token",
    "session",
    "session_id",
    "state",
    "token",
}


def sanitize_analytics_url(value: str | None) -> str | None:
    """Remove credential/PII query parameters and fragments, preserving safe UTMs."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parts = urlsplit(value)
        safe_query = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold().replace("-", "_") not in SENSITIVE_QUERY_KEYS
            and not key.casefold().replace("-", "_").endswith("token")
            and not key.casefold().replace("-", "_").endswith("email")
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_query), ""))
    except (TypeError, ValueError):
        # Malformed referrers are not useful analytics dimensions.
        return None


def sanitize_analytics_path(value: str | None) -> str | None:
    """Store a route path only; query strings never belong in page dimensions."""
    safe_url = sanitize_analytics_url(value)
    if safe_url is None:
        return None
    try:
        return urlsplit(safe_url).path or "/"
    except ValueError:
        return None
