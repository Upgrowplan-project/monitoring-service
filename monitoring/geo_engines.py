"""[21.11 · владелец «да — помоги»: GEO с поиском — Gemini, ChatGPT, Perplexity] Проверки видимости в ответах нейросетей
С ПОИСКОМ в интернете. Прежняя проверка «gemini» спрашивала модель без поиска — она отвечает по памяти (до января 2025,
сама пишет «websites launched after January 2025»), такая цифра не растёт от работы над сайтом. Её ряд сохранён без
изменений для сравнимости; эти проверки — отдельные ряды llm=gemini_search|chatgpt_search|perplexity_search.

Кроме названия в тексте (mentioned) — cited: среди источников ответа есть upgrowplan.com (нейросеть нашла и использовала сайт).
Живые образцы 21.11: OpenAI Responses + web_search — output[type=message].content[0].annotations[url_citation].url,
≈8.2k входных + ≈0.6k выходных токенов + поиск ≈ $0.014 за вопрос; Gemini + google_search на бесплатном ключе — HTTP 429 сразу
(без поиска тот же ключ — 200): поиск Google требует платного уровня проекта. Perplexity — по документации Agent API
(POST /v1/agent, model perplexity/sonar, tools web_search; ссылки — output[type=search_results].results[].url), образца нет."""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

BRAND_DOMAIN = "upgrowplan.com"
Post = Callable[[str, Dict[str, str], Dict[str, Any], float], Tuple[int, Any]]   # (url, headers, json, timeout) → (status, json)


class EngineError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind          # quota | http | parse | exception


ENGINES = {
    "gemini_search": {"label": "Gemini + поиск Google", "key": "GEMINI_API_KEY"},
    "chatgpt_search": {"label": "ChatGPT + поиск", "key": "OPENAI_API_KEY"},
    "perplexity_search": {"label": "Perplexity (Sonar)", "key": "PERPLEXITY_API_KEY"},
}


def _key(cfg, name: str) -> Optional[str]:
    v = getattr(cfg, name, None) or os.getenv(name)
    return v.strip() if v else None


def enabled(cfg) -> List[str]:
    """Проверки, у которых есть ключ и которые не выключены (GEO_ENGINES=chatgpt_search,… — явный список).
    gemini_search — только при GEO_GEMINI_SEARCH=on: на бесплатном ключе поиск Google отвечает 429 (замер 21.11),
    включать после подключения оплаты в Google AI Studio."""
    only = [e.strip() for e in (os.getenv("GEO_ENGINES") or "").split(",") if e.strip()]
    gem_on = (os.getenv("GEO_GEMINI_SEARCH") or "").strip().lower() in ("1", "on", "true", "yes")
    return [e for e, m in ENGINES.items() if _key(cfg, m["key"]) and (not only or e in only)
            and (e != "gemini_search" or gem_on)]


def cited(sources: List[str], domain: str = BRAND_DOMAIN) -> bool:
    return any(domain in (s or "").lower() for s in sources)


# ── разбор ответов (чистые функции — гейт) ──────────────────────────────────

def parse_openai(j: Dict[str, Any]) -> Tuple[str, List[str]]:
    texts, urls = [], []
    for o in j.get("output") or []:
        if o.get("type") != "message":
            continue
        for c in o.get("content") or []:
            if c.get("text"):
                texts.append(c["text"])
            urls += [a.get("url") for a in c.get("annotations") or [] if a.get("url")]
    if not texts:
        raise EngineError("parse", "в ответе OpenAI нет текста")
    return "\n".join(texts), list(dict.fromkeys(urls))


def parse_gemini(j: Dict[str, Any]) -> Tuple[str, List[str]]:
    cands = j.get("candidates") or []
    if not cands:
        raise EngineError("parse", "в ответе Gemini нет candidates")
    c = cands[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts") or [])
    gm = c.get("groundingMetadata") or {}
    # uri у Gemini — переадресация vertexaisearch; домен источника — в title
    srcs = []
    for ch in gm.get("groundingChunks") or []:
        w = ch.get("web") or {}
        srcs += [x for x in (w.get("title"), w.get("uri")) if x]
    return text, list(dict.fromkeys(srcs))


def parse_perplexity(j: Dict[str, Any]) -> Tuple[str, List[str]]:
    texts, urls = [], []
    for o in j.get("output") or []:
        if o.get("type") == "message":
            for c in o.get("content") or []:
                if c.get("text"):
                    texts.append(c["text"])
                urls += [a.get("url") for a in c.get("annotations") or [] if a.get("url")]
        elif o.get("type") == "search_results":
            urls += [r.get("url") for r in o.get("results") or [] if r.get("url")]
    if not texts:
        raise EngineError("parse", "в ответе Perplexity нет текста")
    return "\n".join(texts), list(dict.fromkeys(urls))


def _http_post(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Tuple[int, Any]:
    import httpx
    r = httpx.post(url, headers=headers, json=body, timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:300]


def ask(engine: str, query: str, cfg=None, post: Optional[Post] = None) -> Dict[str, Any]:
    """Один вопрос одной нейросети с поиском → {text, sources, cited}. Ошибка — EngineError (kind=quota прекращает ряд)."""
    post = post or _http_post
    key = _key(cfg, ENGINES[engine]["key"])
    if engine == "chatgpt_search":
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": f"Bearer {key}"}
        body = {"model": os.getenv("GEO_OPENAI_MODEL") or "gpt-4.1-mini", "tools": [{"type": "web_search"}],
                "input": query, "max_output_tokens": 1200}
        parse = parse_openai
    elif engine == "gemini_search":
        model = os.getenv("GEO_GEMINI_SEARCH_MODEL") or os.getenv("GEO_GEMINI_MODEL") or "gemini-3.5-flash-lite"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        headers = {}
        body = {"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}],
                "generationConfig": {"maxOutputTokens": 1200}}
        parse = parse_gemini
    elif engine == "perplexity_search":
        url = "https://api.perplexity.ai/v1/agent"
        headers = {"Authorization": f"Bearer {key}"}
        body = {"model": os.getenv("GEO_PERPLEXITY_MODEL") or "perplexity/sonar", "input": query,
                "tools": [{"type": "web_search"}]}
        parse = parse_perplexity
    else:
        raise ValueError(engine)
    try:
        code, j = post(url, headers, body, 120.0)
    except Exception as e:
        raise EngineError("exception", f"{type(e).__name__}: {str(e)[:150]}")
    if code == 429:
        msg = ((j or {}).get("error") or {}).get("message", "") if isinstance(j, dict) else str(j)
        raise EngineError("quota", f"HTTP 429: {str(msg)[:200]}")
    if code in (401, 402, 403):
        raise EngineError("quota", f"HTTP {code}: {str(j)[:200]}")     # ключ/оплата — дальше по ряду не идём
    if code != 200 or not isinstance(j, dict):
        raise EngineError("http", f"HTTP {code}: {str(j)[:200]}")
    text, sources = parse(j)
    return {"text": text, "sources": sources, "cited": cited(sources)}
