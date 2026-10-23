"""Privacy helpers: identifier redaction, session-key hashing and log scrubbing."""

from __future__ import annotations

import hashlib
import logging
import re

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?im)^\s*(patient(?:'s)?\s*name|name|pt\.? name)\s*[:\-].*$"), r"\1: [REDACTED]"),
    (re.compile(r"(?im)\b(uhid|mrn|ip\s*no|op\s*no|reg(?:istration)?\s*no|patient\s*id|policy\s*(?:no|number))\s*[:#\-]?\s*[\w\-/]+"), r"\1: [REDACTED]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), "[PHONE]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[ID-NUMBER]"),  # Aadhaar-like
    (re.compile(r"(?im)\b(dob|date of birth)\s*[:\-]?\s*[\d/.\-]+"), r"\1: [REDACTED]"),
)

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)(api[_-]?key|seed|token|secret)\s*[=:]\s*\S+"),
)


def redact_identifiers(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def redact_secrets(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[SECRET]", text)
    return text


def session_key(sender: str) -> str:
    """Store a hash of the sender address rather than the address itself."""
    return hashlib.sha256(sender.encode()).hexdigest()[:32]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        return True


def summarize_for_log(text: str, limit: int = 60) -> str:
    """Never log medical content verbatim: keep length + a short hash."""
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    return f"<{len(text)} chars sha={digest}>"
