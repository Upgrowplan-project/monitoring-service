"""[20.11 · владелец: «все состояния сервисов и провайдеров могли быть прочитаны самим MRS на проде прямо перед запуском»;
«в мониторинге, отдельный пункт меню»] Состояние поставщиков данных: остаток, на сколько прогонов хватит, статус.

Правило (зафиксировано до кода, 20.11):
  down      — поставщик не ответил / отклонил ключ / ответ не разобрать;
  exhausted — остатка не хватит даже на один прогон (остаток < расход на прогон) или остаток ≤ 0;
  low       — хватит меньше чем на low_runs прогонов (справочник, 5) или денег меньше low_below;
  ok        — иначе;
  unknown   — нет ключа или у поставщика нет способа узнать остаток (CSE, Exa, OpenAI — пока по журналу/вручную).
Расход на прогон — из справочника providers_catalog.json (одно место), не из этого кода.
Запросы остатка у Tavily, SerpApi, DataForSEO, Apify бесплатны (живой образец ответов снят 20.11)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

CATALOG_PATH = Path(__file__).resolve().parent / "providers_catalog.json"
# ok/low/exhausted/down → словарь AlertManager (healthy/degraded/down); unknown — без тревог
ALERT_STATUS = {"ok": "healthy", "low": "degraded", "exhausted": "down", "down": "down"}

Fetch = Callable[[str, str, Dict[str, Any]], Tuple[Optional[int], Any]]   # (method, url, kwargs) → (status, json)


def catalog() -> Dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _env(name: str, config=None) -> Optional[str]:
    return getattr(config, name, None) or os.getenv(name) or None


def classify(remaining: Optional[float], per_run: Optional[float], low_runs: int,
             low_below: Optional[float] = None) -> Tuple[str, Optional[float]]:
    """→ (status, runs_left). Чистая функция — гейт правила."""
    if remaining is None:
        return "unknown", None
    runs_left = round(remaining / per_run, 1) if per_run else None
    if remaining <= 0 or (runs_left is not None and runs_left < 1):
        return "exhausted", runs_left
    if (runs_left is not None and runs_left < low_runs) or (low_below is not None and remaining < low_below):
        return "low", runs_left
    return "ok", runs_left


# ── разбор ответов (по живому образцу 20.11) ─────────────────────────────────

def parse_tavily(j: Dict[str, Any]) -> Dict[str, Any]:
    acc = j.get("account") or {}
    plan_limit, plan_usage = acc.get("plan_limit"), acc.get("plan_usage") or 0
    paygo_limit, paygo_usage = acc.get("paygo_limit") or 0, acc.get("paygo_usage") or 0
    if plan_limit is None:
        raise ValueError("нет account.plan_limit")
    free_left = max(0.0, float(plan_limit) - float(plan_usage))
    paygo_left = max(0.0, float(paygo_limit) - float(paygo_usage))
    return {"remaining": free_left + paygo_left, "limit": float(plan_limit) + float(paygo_limit), "used": float(plan_usage) + float(paygo_usage),
            "detail": {"plan": acc.get("current_plan"), "free_left": free_left, "paygo_left": paygo_left,
                       "paygo_usage": paygo_usage, "paygo_limit": paygo_limit}}


def parse_serpapi(j: Dict[str, Any]) -> Dict[str, Any]:
    left = j.get("total_searches_left", j.get("plan_searches_left"))
    if left is None:
        raise ValueError("нет total_searches_left")
    return {"remaining": float(left), "limit": j.get("searches_per_month"), "used": j.get("this_month_usage"),
            "detail": {"plan": j.get("plan_name"), "rate_limit_per_hour": j.get("account_rate_limit_per_hour")}}


def parse_dataforseo(j: Dict[str, Any]) -> Dict[str, Any]:
    if j.get("status_code") != 20000:
        raise ValueError(f"status_code {j.get('status_code')}: {j.get('status_message')}")
    money = (((j.get("tasks") or [{}])[0].get("result") or [{}])[0] or {}).get("money") or {}
    if money.get("balance") is None:
        raise ValueError("нет money.balance")
    return {"remaining": round(float(money["balance"]), 4), "limit": None, "used": None, "detail": {"total_paid": money.get("total")}}


def parse_apify(j: Dict[str, Any]) -> Dict[str, Any]:
    d = j.get("data") or {}
    used = float((d.get("current") or {}).get("monthlyUsageUsd") or 0)
    cap = (d.get("limits") or {}).get("maxMonthlyUsageUsd")
    if cap is None:
        raise ValueError("нет limits.maxMonthlyUsageUsd")
    cycle = d.get("monthlyUsageCycle") or {}
    return {"remaining": round(float(cap) - used, 4), "limit": float(cap), "used": round(used, 4),
            "resets_at": cycle.get("endAt"), "detail": {"cycle_start": cycle.get("startAt")}}


def _requests(config) -> Dict[str, Optional[Tuple[str, str, Dict[str, Any]]]]:
    """Запрос остатка для каждого поставщика с check=api; None — нет ключа."""
    tav, serp, apify = _env("TAVILY_API_KEY", config), _env("SERP_API_KEY", config), \
        _env("APIFY_API_TOKEN", config) or _env("APIFY_API_KEY", config)
    dfs_login, dfs_pass = _env("DATAFORSEO_LOGIN", config), _env("DATAFORSEO_PASSWORD", config)
    return {
        "tavily": ("GET", "https://api.tavily.com/usage", {"headers": {"Authorization": f"Bearer {tav}"}}) if tav else None,
        "serpapi": ("GET", "https://serpapi.com/account.json", {"params": {"api_key": serp}}) if serp else None,
        "dataforseo": ("GET", "https://api.dataforseo.com/v3/appendix/user_data", {"auth": (dfs_login, dfs_pass)})
        if dfs_login and dfs_pass else None,
        "apify": ("GET", "https://api.apify.com/v2/users/me/limits", {"params": {"token": apify}}) if apify else None,
    }


PARSERS = {"tavily": parse_tavily, "serpapi": parse_serpapi, "dataforseo": parse_dataforseo, "apify": parse_apify}


def _http_fetch(method: str, url: str, kwargs: Dict[str, Any]) -> Tuple[Optional[int], Any]:
    import httpx
    r = httpx.request(method, url, timeout=30, **kwargs)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def check_all(config=None, fetch: Optional[Fetch] = None) -> List[Dict[str, Any]]:
    """Один проход по справочнику → список результатов (без записи в базу). fetch — подмена для гейта."""
    cat = catalog()
    low_runs = int(cat.get("low_runs") or 5)
    reqs = _requests(config)
    fetch = fetch or _http_fetch
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out = []
    for p in cat["providers"]:
        res: Dict[str, Any] = {"provider": p["id"], "checked_at": now, "remaining": None, "limit": None, "used": None,
                               "runs_left": None, "resets_at": None, "error": None, "detail": {}}
        if p.get("check") != "api":
            res["status"] = "unknown"
            res["error"] = "остаток через API не отдаётся — " + ("по журналу вызовов" if p.get("check") == "journal" else "смотреть в кабинете")
        elif not reqs.get(p["id"]):
            res["status"], res["error"] = "unknown", "в мониторинге нет ключа этого поставщика"
        else:
            method, url, kw = reqs[p["id"]]
            try:
                code, body = fetch(method, url, kw)
            except Exception as e:
                code, body = None, f"{type(e).__name__}: {str(e)[:160]}"
            if code != 200 or not isinstance(body, dict):
                res["status"] = "down"
                res["error"] = f"HTTP {code}: {str(body)[:200]}" if code else f"нет ответа: {body}"
            else:
                try:
                    parsed = PARSERS[p["id"]](body)
                    res.update({k: parsed.get(k) for k in ("remaining", "limit", "used", "resets_at", "detail")})
                    res["status"], res["runs_left"] = classify(parsed["remaining"], p.get("per_run"), low_runs, p.get("low_below"))
                except Exception as e:
                    res["status"], res["error"] = "down", f"ответ не разобран: {e}"
        out.append(res)
    return out


def view(latest: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Справочник + последний замер по каждому поставщику — то, что отдаёт API и показывает меню."""
    rows = []
    for p in catalog()["providers"]:
        m = latest.get(p["id"]) or {}
        rows.append({**{k: p.get(k) for k in ("id", "name", "used_by", "role", "unit", "per_run", "per_run_source",
                                              "reset", "topup_url", "notes", "check")},
                     "status": m.get("status") or "unknown", "remaining": m.get("remaining"), "limit": m.get("limit"),
                     "used": m.get("used"), "runs_left": m.get("runs_left"), "resets_at": m.get("resets_at"),
                     "error": m.get("error"), "detail": m.get("detail") or {},
                     "checked_at": m["checked_at"].isoformat() if m.get("checked_at") else None})
    return rows
