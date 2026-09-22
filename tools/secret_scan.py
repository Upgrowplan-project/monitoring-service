#!/usr/bin/env python3
"""
Pre-commit secret scan (audit 2026-09, P1). Standard library only — no install step.

Blocks a commit when the STAGED changes contain something that looks like a live credential:
  - known key shapes (OpenAI, AWS, GitHub, Google, Slack, Stripe, private keys, JWT-like blobs)
  - assignments such as  API_KEY=<long random value>  outside *.example / templates
  - any staged .env file that is not an example/template

Usage (from the hook):   python tools/secret_scan.py --staged
Bypass for a single line: append   # secret-scan: allow   (or  // secret-scan: allow)
Bypass for one commit:    SKIP_SECRET_SCAN=1 git commit ...   (leave a reason in the message)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ALLOW_MARK = "secret-scan: allow"

# (label, regex) — high-precision shapes first.
SHAPES = [
    ("OpenAI key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("Heroku/Postgres URL with password", re.compile(r"\b(?:postgres(?:ql)?|redis|rediss|amqps?|mongodb(?:\+srv)?)://[^:\s/]+:[^@\s]{6,}@")),
    ("Brevo/SendGrid key", re.compile(r"\b(?:xkeysib-[A-Za-z0-9\-]{40,}|SG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})")),
]
# Generic assignment: NAME_WITH_SECRET_WORD = "long value". Lower precision → only outside templates.
GENERIC = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:API_KEY|APIKEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY)[A-Z0-9_]*\s*[:=]\s*['\"]?([A-Za-z0-9_\-+/=.]{20,})['\"]?"
)
GENERIC_FALSE_POSITIVES = re.compile(
    r"(?i)^(?:\$\{|process\.env|os\.getenv|os\.environ|settings\.|config\.|env\(|<|your[-_]|changeme|example|placeholder|xxx|test-secret|dummy|sk-your)"
)

TEMPLATE_NAMES = re.compile(r"(?i)(?:^|/)(?:\.env\.example|\.env\.template|\.env\.sample|.*\.example|.*\.sample|.*\.md|.*\.rst)$")
ENV_FILE = re.compile(r"(?i)(?:^|/)\.env(?:\.[A-Za-z0-9_-]+)?$")
SKIP_PATH = re.compile(r"(?:^|/)(?:node_modules|\.venv|venv|dist|build|\.next|__pycache__)/|\.(?:png|jpg|jpeg|gif|webp|ico|pdf|docx|xlsx|zip|woff2?|ttf|lock)$")


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def staged_files() -> list[str]:
    out = run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [f for f in out.splitlines() if f.strip()]


def added_lines(path: str) -> list[tuple[int, str]]:
    diff = run(["git", "diff", "--cached", "-U0", "--", path])
    result, lineno = [], 0
    for line in diff.splitlines():
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.append((lineno, line[1:]))
            lineno += 1
        elif not line.startswith("-"):
            lineno += 1
    return result


def scan_line(path: str, text: str) -> list[str]:
    if ALLOW_MARK in text:
        return []
    hits = []
    for label, rx in SHAPES:
        if rx.search(text):
            hits.append(label)
    if not TEMPLATE_NAMES.search(path):
        m = GENERIC.search(text)
        if m and not GENERIC_FALSE_POSITIVES.search(m.group(1)):
            value = m.group(1)
            # require some entropy: at least 3 classes among lower/upper/digit/punct
            classes = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[_\-+/=.]"))
            if classes >= 3:
                hits.append("credential-looking assignment")
    return hits


def main() -> int:
    if os.getenv("SKIP_SECRET_SCAN") == "1":
        print("[secret-scan] SKIP_SECRET_SCAN=1 -> skipped by request.")
        return 0
    findings = []
    for path in staged_files():
        if SKIP_PATH.search(path):
            continue
        if ENV_FILE.search(path) and not TEMPLATE_NAMES.search(path):
            findings.append((path, 0, "staged .env file (real environment file must never be committed)"))
            continue
        for lineno, text in added_lines(path):
            for label in scan_line(path, text):
                findings.append((path, lineno, label))
    if not findings:
        print("[secret-scan] OK - no credential-looking content in staged changes.")
        return 0
    print("[secret-scan] BLOCKED - possible secrets in staged changes:")
    for path, lineno, label in findings:
        print(f"  {path}:{lineno}  {label}")
    print("  Fix: move the value to the environment / .env (ignored), keep only a placeholder.")
    print(f"  False positive: add `{ALLOW_MARK}` to that line, or SKIP_SECRET_SCAN=1 for one commit.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
