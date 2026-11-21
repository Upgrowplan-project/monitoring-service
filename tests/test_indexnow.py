"""[21.11 · владелец «да» на п.1] monitoring/indexnow.py + indexnow_task.

Правило (до кода): отправляется адрес, которого нет среди отправленных или у которого другая lastmod; ответ 200/202 —
адреса помечаются отправленными; иначе — нет (повтор в следующий проход); карта не прочиталась — сбой виден, без отправки."""
from monitoring import indexnow as IN
from monitoring import tasks

BLOG = """<urlset><url><loc>https://www.upgrowplan.com/blog/a</loc><lastmod>2026-11-12</lastmod></url>
<url><loc>https://www.upgrowplan.com/ru/blog/a</loc><lastmod>2026-11-12T00:00:00Z</lastmod></url></urlset>"""
STATIC = "<urlset><url><loc>https://www.upgrowplan.com/about</loc></url></urlset>"


def test_parse_and_diff():
    cur = IN.parse_sitemap(BLOG + STATIC)
    assert cur == {"https://www.upgrowplan.com/blog/a": "2026-11-12", "https://www.upgrowplan.com/ru/blog/a": "2026-11-12",
                   "https://www.upgrowplan.com/about": ""}
    assert IN.changed(cur, {}) == sorted(cur)
    assert IN.changed(cur, dict(cur)) == []
    assert IN.changed(cur, dict(cur, **{"https://www.upgrowplan.com/blog/a": "2026-10-01"})) == ["https://www.upgrowplan.com/blog/a"]


def test_task_submits_only_new_and_changed(monkeypatch):
    from monitoring.database import Base, SessionLocal, engine
    from monitoring.models import IndexNowUrl
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.query(IndexNowUrl).delete()
    db.commit()
    db.close()
    pages = {IN.SITEMAPS[0]: BLOG, IN.SITEMAPS[1]: STATIC}
    sent = []

    def get(u):
        return 200, pages[u]

    def post(url, payload):
        sent.append(sorted(payload["urlList"]))
        assert payload["key"] == IN.KEY and payload["keyLocation"].endswith(IN.KEY + ".txt")
        return 202

    assert tasks.indexnow_task(get, post)["submitted"] == 3
    assert tasks.indexnow_task(get, post)["submitted"] == 0 and len(sent) == 1          # повтор — ничего
    pages[IN.SITEMAPS[0]] = BLOG.replace("2026-11-12</lastmod></url>\n", "2026-11-21</lastmod></url>\n", 1)
    assert tasks.indexnow_task(get, post)["submitted"] == 1 and sent[-1] == ["https://www.upgrowplan.com/blog/a"]

    # отказ IndexNow — адреса не помечаются отправленными
    pages[IN.SITEMAPS[1]] = STATIC.replace("/about", "/new-page")
    r = tasks.indexnow_task(get, lambda u, p: 403)
    assert r["status"] == "error" and r["http"] == 403
    assert tasks.indexnow_task(get, post)["submitted"] == 1 and sent[-1] == ["https://www.upgrowplan.com/new-page"]


def test_unreadable_sitemaps_are_visible():
    r = tasks.indexnow_task(lambda u: (503, ""), lambda u, p: 200)
    assert r["status"] == "error" and len(r["failures"]) == 2
