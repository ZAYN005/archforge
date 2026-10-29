"""Settings and API-key handling.

Key lookup order (first one found wins):
  1. a key passed in explicitly (e.g. typed into the GUI for this session)
  2. the DEEPSEEK_API_KEY environment variable
  3. Windows Credential Manager via `keyring` (when the user ticks "remember")

The key is NEVER written to a file, NEVER printed, and NEVER shown in repr().
As soon as it is loaded it is registered with the redactor, so even an
accidental print/log of it comes out masked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import redact

ENV_VAR = "DEEPSEEK_API_KEY"
KEYRING_SERVICE = "ArchForge"
KEYRING_USER = "deepseek"


@dataclass
class Settings:
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"           # required by the task
    budget_usd: float = 1.00                 # hard limit from the professor's email
    usd_to_cny: float = 7.10                 # exchange rate used to convert the budget (editable)
    pricing_mode: str = "auto"               # "auto" = real peak/off-peak price, "peak" = always worst case
    request_timeout_s: float = 300.0
    max_retries: int = 3
    events_path: str = "runs/events.jsonl"
    # repr=False: printing Settings never reveals the key
    api_key: str | None = field(default=None, repr=False)
    key_source: str = "none"

    @property
    def budget_cny(self) -> float:
        return self.budget_usd * self.usd_to_cny

    def has_key(self) -> bool:
        return bool(self.api_key)


def _from_keyring() -> str | None:
    try:
        import keyring  # optional dependency
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def save_key_to_keyring(key: str) -> bool:
    """Store the key in the OS credential store (Windows Credential Manager). Returns success."""
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        return True
    except Exception:
        return False


def load_settings(explicit_key: str | None = None, **overrides) -> Settings:
    s = Settings(**overrides)
    candidates = [
        ("gui", explicit_key),
        ("env", os.environ.get(ENV_VAR)),
        ("keyring", None),   # looked up lazily, only if the first two are empty
    ]
    for source, value in candidates:
        if source == "keyring":
            value = _from_keyring()
        if value and value.strip():
            s.api_key = value.strip()
            s.key_source = source
            break
    redact.register_secret(s.api_key)   # from now on, this exact string is always masked
    return s


def describe_key(s: Settings) -> str:
    """Safe, screenshot-friendly description of the key status (no characters of the key)."""
    return f"configured (source: {s.key_source})" if s.has_key() else "NOT configured"
