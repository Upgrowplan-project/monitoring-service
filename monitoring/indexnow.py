"""[21.11 · владелец «да» на п.1 — IndexNow при публикации] Новые и изменённые адреса сайта → IndexNow (Bing и др.;
поиск ChatGPT опирается на индекс Bing). Скрипт growth-agent/scripts/indexnow_submit.py был только ручным
(«позже вызывается из publish-этапа») — теперь мониторинг сам сверяет карты сайта с тем, что уже отправлял.

Правило: адрес отправляется, если его нет среди отправленных или у него другая дата lastmod. Ключ IndexNow — не секрет
(файл ключа открыто лежит на сайте). Ответ IndexNow: 200/202 — принято; 403 — ключ не подтверждён; 422 — чужой адрес;
429 — слишком часто. Неуспех не помечает адреса отправленными (повтор в следующий проход)."""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

HOST = "www.upgrowplan.com"
KEY = os.getenv("INDEXNOW_KEY") or "118d6600d3e94ebe9663321ebb5f75e3"
SITEMAPS = [f"https://{HOST}/blog-sitemap.xml", f"https://{HOST}/sitemap-0.xml"]
ENDPOINT = "https://api.indexnow.org/indexnow"

URL_RE = re.compile(r"<url>(.*?)</url>", re.S)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>")


def parse_sitemap(xml: str) -> Dict[str, str]:
    """{url: lastmod (ГГГГ-ММ-ДД или '')} — чистая функция."""
    out = {}
    for block in URL_RE.findall(xml or ""):
        loc = LOC_RE.search(block)
        if not loc:
            continue
        lm = LASTMOD_RE.search(block)
        out[loc.group(1)] = lm.group(1)[:10] if lm else ""
    return out


def changed(current: Dict[str, str], submitted: Dict[str, str]) -> List[str]:
    return sorted(u for u, lm in current.items() if u not in submitted or submitted[u] != lm)


def submit(urls: List[str], post: Optional[Callable[[str, Dict[str, Any]], int]] = None) -> int:
    """→ HTTP-код IndexNow (0 — нет связи)."""
    payload = {"host": HOST, "key": KEY, "keyLocation": f"https://{HOST}/{KEY}.txt", "urlList": urls[:10000]}
    if post is not None:
        return post(ENDPOINT, payload)
    import httpx
    try:
        return httpx.post(ENDPOINT, json=payload, timeout=30,
                          headers={"Content-Type": "application/json; charset=utf-8"}).status_code
    except Exception:
        return 0


def fetch_sitemaps(get: Optional[Callable[[str], Tuple[int, str]]] = None) -> Tuple[Dict[str, str], List[str]]:
    """Все адреса обеих карт + список отказов (карта не прочиталась — её адреса не считаются «исчезнувшими»)."""
    if get is None:
        import httpx

        def get(u):
            r = httpx.get(u, timeout=60, follow_redirects=True)
            return r.status_code, r.text
    urls, failures = {}, []
    for sm in SITEMAPS:
        try:
            code, text = get(sm)
        except Exception as e:
            failures.append(f"{sm}: {type(e).__name__}")
            continue
        if code != 200:
            failures.append(f"{sm}: HTTP {code}")
            continue
        urls.update(parse_sitemap(text))
    return urls, failures
