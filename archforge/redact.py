"""Secret redaction.

Every string that leaves the program (log file, GUI panel, console, error
message) passes through `redact()` first. Two layers of protection:

1. Exact match: the real API key is registered at startup with
   `register_secret()`. Any occurrence of that exact string is replaced.
   This catches the key even if it doesn't look like a typical key.
2. Pattern match: anything shaped like a key (sk-..., Bearer ...) is
   replaced, in case a different/unregistered key shows up (e.g. pasted
   by mistake into an input file or echoed in an error from the server).
"""

from __future__ import annotations

import re
import threading
from typing import Any

MASK = "***REDACTED***"

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),                 # OpenAI/DeepSeek-style keys
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),    # Authorization headers
]

_secrets: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Remember an exact secret value so it is always masked."""
    if value and len(value) >= 8:          # never register tiny strings (would mask normal text)
        with _lock:
            _secrets.add(value)


def redact(text: Any) -> Any:
    """Return `text` with all secrets masked. Non-strings are returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    with _lock:
        secrets = sorted(_secrets, key=len, reverse=True)   # longest first
    for s in secrets:
        text = text.replace(s, MASK)
    for p in _PATTERNS:
        if p.groups:   # keep the prefix ("Bearer ", "api_key=") and mask only the value
            text = p.sub(lambda m: m.group(1) + MASK, text)
        else:
            text = p.sub(MASK, text)
    return text


def redact_obj(obj: Any) -> Any:
    """Recursively redact every string inside dicts/lists/tuples (used for JSON log events)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {redact(str(k)): redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj
