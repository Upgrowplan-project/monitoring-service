"""[18.11 · владелец «принимается!» п.5 программы 17.11 — «канарейка Monitoring: DRA извлекает цены, ежедневно на 3 сайтах»]
Ежедневная проверка, что Deep Research Agent (DRA) не просто отвечает на /health, а ДЕЛАЕТ работу, от которой зависит цепочка
отчёта: извлекает цены со страниц конкурентов (POST /api/extract_prices — тот же вызов, что MRS).

Почему: агент 17.11 — «Apify invalid token 5 дней», DRA 503 в октябре; 16.11 DRA падал по памяти (видео 328 МБ) — /health при этом
был зелёным. Прибор на поставляемом действии, а не на «процесс жив» (И1).

Страницы выбраны замером 18.11 06:23 на прод-DRA (5 кандидатов, HTTP 200 за 30 с, 43 цены): livepilates.gr 10, noesis-pilates.com 11,
upmetrics.co 10 (liveplan 5, pilatesflow 7 — не взяты). Правило (зафиксировано до кода): страница «есть цены» — facts_count ≥ 1;
все 3 — healthy; 1–2 — degraded; 0 / ошибка DRA (в т.ч. {"_dra_error": true} при статусе 200) / нет ответа — down.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SERVICE_NAME = "DRA price extraction"
PAGES: List[str] = [
    "https://livepilates.gr/en/prices/",
    "https://www.noesis-pilates.com/",
    "https://upmetrics.co/pricing",
]
PRODUCT = "pilates studio / business plan software"
LOCATION = "Athens"
TIMEOUT_S = float(os.getenv("DRA_CANARY_TIMEOUT_SECONDS", "420"))


def dra_base_url(config) -> Optional[str]:
    """Адрес DRA: DRA_CANARY_URL, иначе запись «Deep Research …» из MONITORED_SERVICES (тот же список, что проверка здоровья)."""
    explicit = os.getenv("DRA_CANARY_URL")
    if explicit:
        return explicit.rstrip("/")
    for s in getattr(config, "MONITORED_SERVICES", None) or []:
        name = str((s or {}).get("name") or "").lower()
        if "deep research" in name or name in ("dra", "deep-research-agent"):
            return str(s.get("url") or "").rstrip("/") or None
    return None


def evaluate(status_code: Optional[int], body: Any, error: str = "") -> Dict[str, Any]:
    """→ {status, error_message, metadata{pages, priced, total_facts}} по ответу DRA. Чистая функция (гейт)."""
    meta: Dict[str, Any] = {"pages": [], "priced": 0, "total_facts": 0, "expected": len(PAGES)}
    if error or status_code is None:
        return {"status": "down", "error_message": f"DRA не ответил: {error or 'нет ответа'}", "metadata": meta}
    if status_code != 200:
        return {"status": "down", "error_message": f"DRA ответил HTTP {status_code}", "metadata": meta}
    if not isinstance(body, dict):
        return {"status": "down", "error_message": "DRA ответил не JSON", "metadata": meta}
    if body.get("_dra_error"):
        return {"status": "down", "error_message": f"DRA ошибка внутри ответа: {body.get('status_code')} {str(body.get('detail') or '')[:160]}",
                "metadata": meta}
    by_url = {str(r.get("url") or ""): r for r in (body.get("results") or []) if isinstance(r, dict)}
    for u in PAGES:
        r = by_url.get(u) or {}
        n = int(r.get("facts_count") or 0)
        meta["pages"].append({"url": u, "facts": n, "outcome": r.get("outcome") or ("missing" if not r else "")})
        meta["priced"] += 1 if n >= 1 else 0
        meta["total_facts"] += n
    meta["outcome_counts"] = body.get("outcome_counts")
    if meta["priced"] == len(PAGES):
        return {"status": "healthy", "error_message": None, "metadata": meta}
    empty = ", ".join(f"{p['url']} ({p['outcome'] or 'нет цен'})" for p in meta["pages"] if p["facts"] < 1)
    if meta["priced"] == 0:
        return {"status": "down", "error_message": f"DRA не извлёк цены ни с одной из {len(PAGES)} страниц: {empty}", "metadata": meta}
    return {"status": "degraded", "error_message": f"DRA извлёк цены с {meta['priced']} из {len(PAGES)} страниц; без цен: {empty}",
            "metadata": meta}


def run(base_url: Optional[str], post: Optional[Callable[[str, Dict[str, Any], float], Any]] = None) -> Dict[str, Any]:
    """Один вызов DRA (3 страницы) → результат evaluate + секунды. post(url, json, timeout) → (status_code, body) — подмена для гейта."""
    t0 = time.monotonic()
    if not base_url:
        return {"status": "down", "error_message": "адрес DRA не задан (DRA_CANARY_URL / MONITORED_SERVICES)",
                "metadata": {"pages": [], "priced": 0, "total_facts": 0, "expected": len(PAGES)}, "seconds": 0.0}
    payload = {"urls": PAGES, "product": PRODUCT, "location": LOCATION}
    code, body, err = None, None, ""
    try:
        if post is not None:
            code, body = post(f"{base_url}/api/extract_prices", payload, TIMEOUT_S)
        else:
            import httpx
            r = httpx.post(f"{base_url}/api/extract_prices", json=payload, timeout=TIMEOUT_S)
            code = r.status_code
            try:
                body = json.loads(r.text.strip() or "null")      # DRA шлёт пробелы, пока работает (keep-alive), JSON — в конце
            except ValueError:
                body = None
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:160]}"
    res = evaluate(code, body, err)
    res["seconds"] = round(time.monotonic() - t0, 1)
    res["metadata"]["seconds"] = res["seconds"]
    return res
