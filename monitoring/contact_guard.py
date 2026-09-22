"""
Guard for the public contact form (audit 2026-09, P1).

- ContactIn: strict field validation (lengths, plausible e-mail, no header/newline tricks)
- ContactLimiter: per-IP sliding window, in-process (one dyno) — stops mail floods and
  keeps the auto-reply from becoming a relay that mails arbitrary third parties.
- html_escape_name: the name is interpolated into the auto-reply HTML.
"""
from __future__ import annotations

import html
import re
import threading
import time
from collections import deque
from typing import Deque, Dict

from pydantic import BaseModel, Field, field_validator

# Deliberately simple: one "@", a dot in the domain, no whitespace/newlines. RFC-full
# validation would need the email-validator package; this rejects what we care about.
_EMAIL_RE = re.compile(r"^[^\s@<>,;\"']{1,64}@[^\s@<>,;\"']{1,190}\.[A-Za-z]{2,24}$")


class ContactIn(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("name")
    @classmethod
    def _name_no_newlines(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if any(ch in v for ch in "\r\n\x00"):
            raise ValueError("invalid name")
        return v or None

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.fullmatch(v):
            raise ValueError("invalid email")
        return v.lower()

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("empty message")
        return v


def html_escape_name(name: str | None) -> str:
    return html.escape(name, quote=True) if name else ""


class ContactLimiter:
    def __init__(self, max_calls: int = 3, window_seconds: int = 3600):
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.window
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            if len(self._hits) > 10_000:
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff][:1000]:
                    self._hits.pop(k, None)
            return True


def client_ip(request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


contact_limiter = ContactLimiter(max_calls=3, window_seconds=3600)
