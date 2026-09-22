"""
Авторизация доступа к API мониторинга.

Модель:
- ADMIN-only чтение/действия: валидный JWT (HS512, общий JWT_SECRET с user-service)
  с claim role == ADMIN. Проверяется по подписи, без обращения к user-service.
- Server-to-server ingest (market-research-service → monitoring): отдельный
  заголовок X-Ingest-Token == MONITORING_INGEST_TOKEN.
- Публичные эндпоинты (beacon, оценки, контакт-форма) — без авторизации.

Fail-closed (аудит 2026-09, P0): если JWT_SECRET / MONITORING_INGEST_TOKEN не заданы,
охраняемые эндпоинты отвечают 503 — а не открываются. Единственный способ выключить
авторизацию — явный флаг MONITORING_AUTH_DISABLED=1 (только локальная разработка).
"""

import hmac
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Какие префиксы вообще охраняем.
GUARDED_PREFIXES = ("/api/monitoring", "/api/ratings")

# (METHOD, PATH) — публичные эндпоинты (без токена).
PUBLIC_ENDPOINTS = {
    ("POST", "/api/rating"),
    ("POST", "/api/monitoring/pageview"),
    ("POST", "/api/monitoring/contact"),
    # /api/monitoring/reports/debug: was public — moved behind admin-JWT (audit 2026-09).
}

# Server-to-server ingest (нужен X-Ingest-Token, не admin-JWT).
INGEST_ENDPOINTS = {
    ("POST", "/api/monitoring/reports"),
    ("POST", "/api/monitoring/synthesis-logs"),
    ("POST", "/api/monitoring/bot-crawl"),
}


def auth_disabled_explicitly() -> bool:
    """Авторизация выключена ТОЛЬКО явным флагом (dev). Отсутствие секрета ≠ выключено."""
    return os.getenv("MONITORING_AUTH_DISABLED", "").strip() == "1"


def auth_enabled() -> bool:
    return not auth_disabled_explicitly()


def startup_check() -> None:
    """Громко предупредить при старте, если прод-конфигурация неполная."""
    if auth_disabled_explicitly():
        logger.warning("MONITORING_AUTH_DISABLED=1 — авторизация выключена (только для dev!)")
        return
    if not os.getenv("JWT_SECRET"):
        logger.error("JWT_SECRET не задан — admin-эндпоинты будут отвечать 503 (fail-closed)")
    if not os.getenv("MONITORING_INGEST_TOKEN"):
        logger.error("MONITORING_INGEST_TOKEN не задан — ingest-эндпоинты будут отвечать 503 (fail-closed)")


def _verify_admin_token(token: str) -> tuple[bool, bool]:
    """Returns (is_valid_admin, is_expired).

    is_expired=True means the token was valid but timed out → caller should
    return 401 so the frontend refresh-flow kicks in instead of a dead 403.
    """
    secret = os.getenv("JWT_SECRET")
    if not secret:
        return False, False   # fail-closed: без секрета никто не админ
    import jwt  # lazy: PyJWT нужен только когда авторизация включена
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS512"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        return False, True   # expired → 401
    except Exception:
        return False, False  # bad signature / malformed → 403
    role = (payload.get("role") or "").upper()
    return role == "ADMIN", False


def check_request(method: str, path: str, authorization: Optional[str], ingest_token: Optional[str]):
    """
    Возвращает None если запрос разрешён, иначе (status_code, message).
    """
    method = (method or "GET").upper()

    # Не охраняем всё, что вне /api/monitoring и /api/ratings (root, /docs и т.п.).
    if not any(path.startswith(p) for p in GUARDED_PREFIXES):
        return None

    if method == "OPTIONS":  # CORS preflight
        return None

    if not auth_enabled():  # dev: выключено ЯВНЫМ флагом
        return None

    if (method, path) in PUBLIC_ENDPOINTS:
        return None

    if (method, path) in INGEST_ENDPOINTS:
        expected = os.getenv("MONITORING_INGEST_TOKEN")
        if not expected:
            return (503, "Ingest token not configured")  # fail-closed
        if not ingest_token or not hmac.compare_digest(ingest_token, expected):
            return (401, "Invalid ingest token")
        return None

    # Остальное под /api/monitoring и /api/ratings — только ADMIN.
    if not os.getenv("JWT_SECRET"):
        return (503, "Auth not configured")  # fail-closed
    if not authorization or not authorization.startswith("Bearer "):
        return (401, "Missing admin token")
    ok, expired = _verify_admin_token(authorization[7:].strip())
    if not ok:
        # Expired token → 401 so the frontend auto-refresh triggers.
        # Wrong role / bad signature → 403.
        return (401, "Token expired") if expired else (403, "Admin access required")
    return None


def verify_ws_token(token: Optional[str]) -> bool:
    """Для WebSocket: пускаем если auth выключен ЯВНО или токен — валидный admin-JWT."""
    if not auth_enabled():
        return True
    if not token or not os.getenv("JWT_SECRET"):
        return False
    ok, _ = _verify_admin_token(token)
    return ok
