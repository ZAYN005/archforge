"""Phase 1 self-test.  Run:  python -m archforge.selftest

What it proves, in order:
  1. The API key is found (without ever printing it).
  2. The redactor masks the real key.
  3. One real call to deepseek-v4-pro works, and its cost is computed.
  4. Prompt caching works: the same long prefix sent twice -> 2nd call is mostly cache hits.
  5. The event log was written and does NOT contain the key.

Cost: two short calls, roughly ¥0.01-0.03 in total.
"""

from __future__ import annotations

import json
import os
import sys
import time

from . import config, pricing
from .events import EventLog
from .llm import LLMClient
from .redact import MASK, redact

LOG = "runs/selftest-events.jsonl"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))


def stable_prefix() -> str:
    """~1,500 tokens of fixed text, standing in for the real system prompt + spec IR."""
    rules = [f"Rule {i:03d}: generated code must follow the architecture spec, keep modules "
             f"separate, and tag every function with the requirement ID it implements."
             for i in range(1, 61)]
    return "You are ArchForge, a careful software engineer.\n" + "\n".join(rules)


def main() -> int:
    print("ArchForge Phase 1 self-test\n")
    if os.path.exists(LOG):
        os.remove(LOG)

    # 1. key
    s = config.load_settings()
    check("API key found", s.has_key(), config.describe_key(s))
    if not s.has_key():
        print("\nSet the key first:  setx DEEPSEEK_API_KEY \"<your key>\"  then open a NEW terminal.")
        return 1

    # 2. redaction of the real key
    leaked = s.api_key in redact(f"the key is {s.api_key} ok")
    check("Redactor masks the real key", not leaked)

    events = EventLog(LOG)
    llm = LLMClient(s, events)
    peak = pricing.is_peak()
    print(f"\n  Beijing time pricing window: {'PEAK' if peak else 'OFF-PEAK (half price)'}")
    print(f"  Budget: ${s.budget_usd:.2f} = CNY {s.budget_cny:.2f}\n")

    # 3 + 4. two calls with an identical long prefix
    prefix = stable_prefix()
    for i in (1, 2):
        msgs = [{"role": "system", "content": prefix},
                {"role": "user", "content": f"Reply with exactly: ARCHFORGE_OK_{i}"}]
        msg, u, cost = llm.chat(msgs, role="selftest", thinking=False, max_tokens=20)
        print(f"  Call {i}: reply={msg.content!r}")
        print(f"          tokens: cache_hit={u.cache_hit} cache_miss={u.cache_miss} "
              f"output={u.output}  hit_rate={u.hit_rate:.0%}  cost=CNY {cost:.6f}")
        if i == 1:
            check("Real call to deepseek-v4-pro works", f"ARCHFORGE_OK_{i}" in (msg.content or ""))
            time.sleep(3)   # DeepSeek builds the cache asynchronously; give it a moment
        else:
            check("Prompt cache hit on 2nd call", u.cache_hit > 0,
                  f"{u.hit_rate:.0%} of input billed at cache price")

    m = llm.meter
    print(f"\n  Total: {m.calls} calls, CNY {m.spent_cny:.6f} (= ${m.spent_cny / s.usd_to_cny:.6f}), "
          f"{m.spent_cny / m.budget_cny:.3%} of budget")

    # 5. event log
    with open(LOG, encoding="utf-8") as f:
        raw = f.read()
    lines = [json.loads(x) for x in raw.splitlines() if x.strip()]
    check("Event log written", len(lines) >= 2, f"{len(lines)} events in {LOG}")
    check("Key absent from event log", s.api_key not in raw)

    failed = [r for r in results if not r[1]]
    print(f"\n{'ALL CHECKS PASSED' if not failed else f'{len(failed)} CHECK(S) FAILED'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
