"""
Авторизация доступа к API мониторинга.

Модель:
- ADMIN-only чтение/действия: валидный JWT (HS512, общий JWT_SECRET с user-service)
  с claim role == ADMIN. Проверяется по подписи, без обращения к user-service.
- Server-to-server ingest (market-research-service → monitoring): отдельный
  заголовок X-Ingest-Token == MONITORING_INGEST_TOKEN.
- Публичные эндпоинты (beacon, оценки, контакт-форма) — без авторизации.

Если JWT_SECRET не задан — авторизация ВЫКЛЮЧЕНА (удобно для локальной разработки).
В проде JWT_SECRET обязателен, иначе данные открыты.
"""

import os
from typing import Optional

# Какие префиксы вообще охраняем.
GUARDED_PREFIXES = ("/api/monitoring", "/api/ratings")

# (METHOD, PATH) — публичные эндпоинты (без токена).
PUBLIC_ENDPOINTS = {
    ("POST", "/api/rating"),
    ("POST", "/api/monitoring/pageview"),
    ("POST", "/api/monitoring/contact"),
}

# Server-to-server ingest (нужен X-Ingest-Token, не admin-JWT).
INGEST_ENDPOINTS = {
    ("POST", "/api/monitoring/reports"),
    ("POST", "/api/monitoring/synthesis-logs"),
}


def auth_enabled() -> bool:
    return bool(os.getenv("JWT_SECRET"))


def _verify_admin_token(token: str) -> tuple[bool, bool]:
    """Returns (is_valid_admin, is_expired).

    is_expired=True means the token was valid but timed out → caller should
    return 401 so the frontend refresh-flow kicks in instead of a dead 403.
    """
    secret = os.getenv("JWT_SECRET")
    if not secret:
        return True, False
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

    if not auth_enabled():  # dev: токены не настроены — пропускаем
        return None

    if (method, path) in PUBLIC_ENDPOINTS:
        return None

    if (method, path) in INGEST_ENDPOINTS:
        expected = os.getenv("MONITORING_INGEST_TOKEN")
        if not expected:
            return None  # ingest-токен не настроен — не блокируем server-to-server
        if ingest_token != expected:
            return (401, "Invalid ingest token")
        return None

    # Остальное под /api/monitoring и /api/ratings — только ADMIN.
    if not authorization or not authorization.startswith("Bearer "):
        return (401, "Missing admin token")
    ok, expired = _verify_admin_token(authorization[7:].strip())
    if not ok:
        # Expired token → 401 so the frontend auto-refresh triggers.
        # Wrong role / bad signature → 403.
        return (401, "Token expired") if expired else (403, "Admin access required")
    return None


def verify_ws_token(token: Optional[str]) -> bool:
    """Для WebSocket: пускаем если auth выключен или токен — валидный admin-JWT."""
    if not auth_enabled():
        return True
    if not token:
        return False
    ok, _ = _verify_admin_token(token)
    return ok
