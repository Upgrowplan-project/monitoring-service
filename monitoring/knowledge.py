"""[20.11 · владелец «база знаний проекта в облаке»] Правила базы знаний (бывший D:\\UpgrowPlan\\INFO.md).

Повтор = тот же «субъект + факт» после нормализации (регистр, знаки, пробелы) → один ключ, вторая строка не создаётся.
Запись, похожая на секрет (ключ API, токен бота, пароль, номер карты), не принимается — на сервере, а не только у агента."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Optional, Tuple

SECTIONS = {
    "competitors": "Конкуренты — значимые действия",
    "providers": "Поставщики и сервисы — цены, лимиты, условия, сбои",
    "market": "Рынок и отрасль",
    "search_ai": "Поиск и ИИ-поиск (SEO / GEO)",
    "risks": "Риски и инциденты",
    "opportunities": "Возможности — гранты, акселераторы, события",
    "people": "Тестеры, клиенты, партнёры",
}
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{10,}|\b\d{9,10}:[A-Za-z0-9_-]{30,}|AIza[0-9A-Za-z_-]{20,}|"
                       r"(?i:password|пароль|token|токен|api[_ ]?key)\s*[:=]\s*\S+|\b(?:\d[ -]?){13,19}\b)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def norm(s: Optional[str]) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def entry_key(subject: str, fact: str) -> str:
    return hashlib.sha1(f"{norm(subject)}|{norm(fact)}".encode()).hexdigest()[:16]


def validate(e: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """→ (чистая запись, None) или (None, причина отказа). Чистая функция — гейт правил."""
    section, subject, fact = e.get("section"), str(e.get("subject") or "").strip(), str(e.get("fact") or "").strip()
    if section not in SECTIONS:
        return None, f"неизвестный раздел {section!r}"
    if not subject or not fact:
        return None, "нет субъекта или факта"
    if SECRET_RE.search(" ".join([subject, fact, str(e.get("source") or "")])):
        return None, "похоже на секрет — не записано"
    date = str(e.get("date") or "")[:10]
    return {"key": entry_key(subject, fact), "section": section, "subject": subject[:300], "fact": fact,
            "source": (str(e.get("source")).strip() if e.get("source") else None),
            "event_date": date if DATE_RE.match(date) else None,
            "author": str(e.get("author") or "founder-agent")[:50]}, None
