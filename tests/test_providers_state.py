"""[20.11 · владелец «в мониторинге, отдельный пункт меню — сводка и состояние провайдеров»; MRS позже читает перед прогоном]
monitoring/providers.py, providers_check_task, monitoring/knowledge.py, /api/monitoring/providers|knowledge|digests.

Правило (до кода): down — нет ответа / отказ ключа / ответ не разобрать; exhausted — не хватит на 1 прогон; low — меньше
low_runs (5) прогонов или денег меньше low_below; ok — иначе; unknown — нет ключа или остаток не отдаётся.
Тревога — только при смене состояния. Образцы ответов — живые, сняты 20.11 (бесплатные запросы остатка)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-providers")
os.environ.setdefault("MONITORING_INGEST_TOKEN", "test-ingest")
os.environ["MONITORING_READ_TOKEN"] = "test-read"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from monitoring import knowledge as K  # noqa: E402
from monitoring import providers as P  # noqa: E402

# ── живые образцы 20.11 ──
TAVILY = {"key": {"usage": 955, "limit": None}, "account": {"current_plan": "Researcher", "plan_usage": 955, "plan_limit": 1000,
                                                             "paygo_usage": 0, "paygo_limit": 1000.0}}
SERPAPI = {"plan_name": "Free Plan", "searches_per_month": 250, "plan_searches_left": 229, "total_searches_left": 229,
           "this_month_usage": 21, "account_rate_limit_per_hour": 250}
DFS = {"status_code": 20000, "tasks": [{"result": [{"money": {"total": 1, "balance": 0.07199999999999995}}]}]}
APIFY = {"data": {"current": {"monthlyUsageUsd": 0.00044}, "limits": {"maxMonthlyUsageUsd": 5},
                  "monthlyUsageCycle": {"startAt": "2026-11-18T00:00:00.000Z", "endAt": "2026-12-17T23:59:59.999Z"}}}


class Cfg:
    TAVILY_API_KEY = "t"
    SERP_API_KEY = "s"
    DATAFORSEO_LOGIN = "l"
    DATAFORSEO_PASSWORD = "p"
    APIFY_API_TOKEN = "a"


def fake(answers):
    def fetch(method, url, kw):
        for host, ans in answers.items():
            if host in url:
                if isinstance(ans, Exception):
                    raise ans
                return ans
        raise AssertionError(url)
    return fetch


OK_ANSWERS = {"tavily": (200, TAVILY), "serpapi": (200, SERPAPI), "dataforseo": (200, DFS), "apify": (200, APIFY)}


def test_classify_rule():
    assert P.classify(1045, 52, 5) == ("ok", 20.1)
    assert P.classify(200, 52, 5) == ("low", 3.8)
    assert P.classify(45, 52, 5) == ("exhausted", 0.9)       # было бы 45 из 1000 без оплаты за использование
    assert P.classify(0, None, 5) == ("exhausted", None)
    assert P.classify(0.07, None, 5, low_below=1.0) == ("low", None)
    assert P.classify(None, 52, 5) == ("unknown", None)


def test_parsers_on_live_samples():
    t = P.parse_tavily(TAVILY)
    assert t["remaining"] == 1045 and t["detail"]["free_left"] == 45 and t["detail"]["paygo_left"] == 1000
    assert P.parse_serpapi(SERPAPI)["remaining"] == 229
    assert P.parse_dataforseo(DFS)["remaining"] == 0.072
    a = P.parse_apify(APIFY)
    assert a["remaining"] == 4.9996 and a["resets_at"].startswith("2026-12-17")


def test_check_all_statuses_and_failures():
    res = {r["provider"]: r for r in P.check_all(Cfg, fetch=fake(OK_ANSWERS))}
    assert res["tavily"]["status"] == "ok" and res["tavily"]["runs_left"] == 20.1
    assert res["serpapi"]["status"] == "ok"
    assert res["dataforseo"]["status"] == "low"                  # $0.072 < $1
    assert res["apify"]["status"] == "ok"
    assert res["google_cse"]["status"] == "unknown" and "журнал" in res["google_cse"]["error"]
    bad = dict(OK_ANSWERS, serpapi=(401, {"error": "Invalid API key"}), apify=TimeoutError("read timeout"),
               dataforseo=(200, {"status_code": 40100, "status_message": "Unauthorized"}))
    res = {r["provider"]: r for r in P.check_all(Cfg, fetch=fake(bad))}
    assert res["serpapi"]["status"] == "down" and "401" in res["serpapi"]["error"]
    assert res["apify"]["status"] == "down" and "TimeoutError" in res["apify"]["error"]
    assert res["dataforseo"]["status"] == "down" and "40100" in res["dataforseo"]["error"]

    class NoKeys:
        pass
    for k in ("TAVILY_API_KEY", "SERP_API_KEY", "DATAFORSEO_LOGIN", "APIFY_API_TOKEN", "APIFY_API_KEY"):
        os.environ.pop(k, None)
    res = {r["provider"]: r for r in P.check_all(NoKeys, fetch=fake({}))}
    assert res["tavily"]["status"] == "unknown" and "нет ключа" in res["tavily"]["error"]


def test_task_stores_and_alerts_only_on_change(monkeypatch):
    from monitoring import tasks
    from monitoring.alerting import AlertManager
    from monitoring.database import Base, SessionLocal, engine
    from monitoring.models import ProviderCheck, SystemAlert
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()   # с чистого листа: результат зависит только от этого прохода, не от соседних проверок
    db.query(ProviderCheck).delete()
    db.query(SystemAlert).filter(SystemAlert.service_name.like("Provider %")).delete(synchronize_session=False)
    db.commit()
    db.close()
    sent = []

    async def capture(self, alert):
        sent.append(alert.message)
    monkeypatch.setattr(AlertManager, "send_alert", capture)
    monkeypatch.setattr(tasks, "get_config", lambda: Cfg)
    r1 = tasks.providers_check_task(fetch=fake(OK_ANSWERS))
    assert r1["providers"]["dataforseo"] == "low" and r1["alerts"] == 1 and "DataForSEO" in sent[0] and "Пополнить" in sent[0]
    r2 = tasks.providers_check_task(fetch=fake(OK_ANSWERS))
    assert r2["alerts"] == 0                                    # то же состояние — без повторной тревоги
    tav_low = {"account": dict(TAVILY["account"], paygo_usage=900)}   # осталось 145 → 2.8 прогона
    r3 = tasks.providers_check_task(fetch=fake(dict(OK_ANSWERS, tavily=(200, tav_low))))
    assert r3["providers"]["tavily"] == "low" and r3["alerts"] == 1 and "Tavily" in sent[-1]
    r4 = tasks.providers_check_task(fetch=fake(OK_ANSWERS))
    assert r4["alerts"] == 1 and "снова в порядке" in sent[-1]
    db = SessionLocal()
    assert db.query(ProviderCheck).filter(ProviderCheck.provider == "tavily").count() == 4
    assert db.query(SystemAlert).filter(SystemAlert.service_name.like("Provider %")).count() == 3
    db.close()


def test_knowledge_rules():
    a, _ = K.validate({"section": "providers", "subject": "Tavily", "fact": "Использовано 80% лимита."})
    b, _ = K.validate({"section": "providers", "subject": "tavily", "fact": "использовано 80 % лимита!"})
    assert a["key"] == b["key"]
    assert K.validate({"section": "risks", "subject": "Bot", "fact": "token: 9101495456:AAHF9qiQIaR83m8lLajZzUk574KQC4syeYA"})[1]
    assert K.validate({"section": "nonsense", "subject": "X", "fact": "y"})[1]
    c, _ = K.validate({"section": "market", "subject": "X", "fact": "y", "date": "завтра"})
    assert c["event_date"] is None


def test_endpoints_and_access(monkeypatch):
    import main
    from monitoring import tasks
    from monitoring.database import Base, engine
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(tasks, "get_config", lambda: Cfg)
    monkeypatch.setattr(P, "_http_fetch", fake(OK_ANSWERS))
    c = TestClient(main.app)
    ing, rd = {"X-Ingest-Token": "test-ingest"}, {"X-Read-Token": "test-read"}

    r = c.get("/api/monitoring/providers", headers=rd)
    assert r.status_code == 200
    j = r.json()
    by = {p["id"]: p for p in j["providers"]}
    assert by["tavily"]["status"] == "ok" and by["tavily"]["topup_url"] and by["google_cse"]["status"] == "unknown"
    assert c.get("/api/monitoring/providers?refresh=1", headers=rd).json()["refreshed_now"] is True
    assert c.get("/api/monitoring/providers").status_code == 401

    e = [{"section": "providers", "subject": "Tavily", "fact": "Включена оплата за использование.", "date": "2026-11-20"},
         {"section": "providers", "subject": "TAVILY", "fact": "включена оплата за использование"},
         {"section": "risks", "subject": "x", "fact": "password: hunter2"}]
    r = c.post("/api/monitoring/knowledge", json={"entries": e}, headers=ing)
    assert r.status_code == 200 and r.json()["added"] == 1 and len(r.json()["skipped"]) == 2
    assert c.post("/api/monitoring/knowledge", json={"entries": e}, headers=rd).status_code in (401, 403)
    lst = c.get("/api/monitoring/knowledge?section=providers", headers=rd).json()
    assert lst["total"] == 1 and lst["entries"][0]["date"] == "2026-11-20"

    monkeypatch.setenv("KNOWLEDGE_LINK_KEY", "kb-link")
    md = c.get("/api/monitoring/knowledge.md?key=kb-link")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "## Поставщики и сервисы" in md.text and "**Tavily** — Включена оплата за использование." in md.text
    assert c.get("/api/monitoring/knowledge.md", headers=rd).status_code == 200      # пароль на чтение — заголовком
    assert c.get("/api/monitoring/knowledge.md").status_code == 401
    assert c.get("/api/monitoring/knowledge.md?key=wrong").status_code == 401
    assert c.get("/api/monitoring/knowledge.md?key=test-read").status_code == 401    # пароль на чтение в ссылке не работает
    assert c.get("/api/monitoring/providers?key=kb-link").status_code == 401         # ключ ссылки — только база знаний
    assert c.get("/api/monitoring/emails?key=kb-link").status_code == 401
    assert c.post("/api/monitoring/knowledge?key=kb-link", json={"entries": e}).status_code == 401
    monkeypatch.delenv("KNOWLEDGE_LINK_KEY")
    assert c.get("/api/monitoring/knowledge.md?key=kb-link").status_code == 401      # нет ключа в окружении — закрыто

    assert c.post("/api/monitoring/digests", json={"day": "2026-11-20", "text": "v1"}, headers=ing).status_code == 200
    assert c.post("/api/monitoring/digests", json={"day": "2026-11-20", "text": "v2"}, headers=ing).status_code == 200
    d = c.get("/api/monitoring/digests", headers=rd).json()["digests"]
    assert [x["text"] for x in d if x["day"] == "2026-11-20"] == ["v2"]
