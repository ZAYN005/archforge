"""Offline unit tests for Phase 1 (no API calls, no cost).  Run:  python -m pytest -q"""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from archforge import config, pricing, redact
from archforge.events import EventLog
from archforge.llm import BudgetExceeded, CostMeter, LLMClient

FAKE_KEY = "sk-" + "a1b2c3d4" * 4          # built at runtime so no key-shaped literal sits in the repo


# ---------------- redaction ----------------
def test_pattern_redaction():
    out = redact.redact(f"key={FAKE_KEY}")
    assert FAKE_KEY not in out and redact.MASK in out


def test_registered_secret_redaction_even_if_not_key_shaped():
    redact.register_secret("my-weird-secret-123")
    assert "my-weird-secret-123" not in redact.redact("x my-weird-secret-123 y")


def test_bearer_header_keeps_prefix():
    out = redact.redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")
    assert out == f"Authorization: Bearer {redact.MASK}"


def test_nested_object_redaction():
    obj = {"a": [FAKE_KEY, {"b": FAKE_KEY}], "n": 3}
    out = redact.redact_obj(obj)
    assert FAKE_KEY not in json.dumps(out) and out["n"] == 3


def test_normal_text_untouched():
    assert redact.redact("game state: Playing -> Paused") == "game state: Playing -> Paused"


# ---------------- config ----------------
def test_settings_repr_hides_key(monkeypatch):
    monkeypatch.setenv(config.ENV_VAR, FAKE_KEY)
    s = config.load_settings()
    assert s.key_source == "env"
    assert FAKE_KEY not in repr(s)
    assert FAKE_KEY not in config.describe_key(s)


def test_gui_key_beats_env(monkeypatch):
    monkeypatch.setenv(config.ENV_VAR, FAKE_KEY)
    s = config.load_settings(explicit_key="sk-" + "z" * 32)
    assert s.key_source == "gui"


# ---------------- pricing ----------------
@pytest.mark.parametrize("iso,expected", [
    ("2026-10-26T09:00:00+08:00", True),    # Monday 09:00 -> peak starts
    ("2026-10-26T11:59:00+08:00", True),
    ("2026-10-26T12:00:00+08:00", False),   # lunch gap
    ("2026-10-26T14:00:00+08:00", True),
    ("2026-10-26T18:00:00+08:00", False),   # evening
    ("2026-10-24T10:00:00+08:00", False),   # Saturday
    ("2026-10-26T01:30:00+00:00", True),    # 09:30 Beijing given in UTC
])
def test_peak_windows(iso, expected):
    assert pricing.is_peak(datetime.fromisoformat(iso)) is expected


def test_cost_math_offpeak():
    u = pricing.Usage(cache_hit=1_000_000, cache_miss=1_000_000, output=1_000_000)
    sat = datetime.fromisoformat("2026-10-24T10:00:00+08:00")
    assert pricing.cost_cny("deepseek-v4-pro", u, sat) == pytest.approx(0.15 + 4.5 + 13.5)


def test_peak_mode_forces_worst_case():
    u = pricing.Usage(output=1_000_000)
    sat = datetime.fromisoformat("2026-10-24T10:00:00+08:00")
    assert pricing.cost_cny("deepseek-v4-pro", u, sat, mode="peak") == pytest.approx(27.0)


def test_usage_from_api_object():
    api = SimpleNamespace(prompt_cache_hit_tokens=900, prompt_cache_miss_tokens=100,
                          completion_tokens=50,
                          completion_tokens_details=SimpleNamespace(reasoning_tokens=30))
    u = pricing.Usage.from_api(api)
    assert (u.cache_hit, u.cache_miss, u.output, u.reasoning) == (900, 100, 50, 30)
    assert u.hit_rate == pytest.approx(0.9)


# ---------------- budget guard (with a fake API client) ----------------
class FakeClient:
    """Stands in for the OpenAI client; counts calls, returns a fixed usage."""
    def __init__(self):
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls += 1
        msg = SimpleNamespace(content="ok", tool_calls=None, reasoning_content=None)
        usage = SimpleNamespace(prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=1000,
                                completion_tokens=500, completion_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=usage)


def test_budget_guard_blocks_before_spending(tmp_path):
    s = config.Settings(budget_usd=0.0001)              # ~0.0007 CNY: too small for any call
    fake = FakeClient()
    llm = LLMClient(s, EventLog(str(tmp_path / "e.jsonl")), client=fake)
    with pytest.raises(BudgetExceeded):
        llm.chat([{"role": "user", "content": "hi"}])
    assert fake.calls == 0                              # the API was never contacted


def test_meter_accumulates_by_role(tmp_path):
    s = config.Settings(budget_usd=1.0)
    llm = LLMClient(s, EventLog(str(tmp_path / "e.jsonl")), client=FakeClient())
    llm.chat([{"role": "user", "content": "a"}], role="coder")
    llm.chat([{"role": "user", "content": "b"}], role="tester")
    assert llm.meter.calls == 2
    assert set(llm.meter.by_role) == {"coder", "tester"}
    assert llm.meter.spent_cny > 0


# ---------------- event log ----------------
def test_event_log_never_contains_key(tmp_path):
    p = tmp_path / "e.jsonl"
    log = EventLog(str(p))
    log.emit("oops", note=f"accidentally logged {FAKE_KEY}", nested={"k": FAKE_KEY})
    raw = p.read_text(encoding="utf-8")
    assert FAKE_KEY not in raw
    assert json.loads(raw.splitlines()[0])["seq"] == 1
