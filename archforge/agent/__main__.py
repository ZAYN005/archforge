"""Demo:  python -m archforge.agent [--task "..."] [--workspace DIR] [--thinking]

Runs ONE real agent on a small, self-checking task and prints every step live.
Proves the loop works end to end: plan -> write -> run -> read error -> fix -> run -> report.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from .. import config
from ..events import EventLog
from ..llm import LLMClient
from .loop import AgentLoop
from .prompts import build_system_prompt
from .sandbox import Sandbox
from .tools import ToolBox, ToolContext

DEMO_TASK = """Create a small Node.js module `fraction.js` (CommonJS, no dependencies) that exports:
- parse(s): parse "n/d" (also "-n/d" and integers like "3") into {n, d} with d > 0; throw an Error on d = 0 or bad input
- simplify(f): reduce to lowest terms, sign kept in n
- add(a, b): add two fraction strings, return a simplified string like "5/6" (or "2" when d = 1)
- equals(a, b): true when the two fraction strings have the same value ("1/2" equals "2/4")
Then write `test.js` using only node:assert with at least 8 checks (including negatives, zero denominator, equals).
Acceptance: `node test.js` exits with code 0 and prints "ALL TESTS PASSED". Run it to prove it."""


def _printer(t0):
    def show(e):
        k, el = e["kind"], f"{time.time() - t0:5.1f}s"
        if k == "llm_call":
            print(f"  {el}  [model]  {e['tokens']['cache_miss']}+{e['tokens']['cache_hit']}c in / "
                  f"{e['tokens']['output']} out tokens, CNY {e['cost_cny']:.4f}  ->  "
                  f"{', '.join(e['tool_calls']) or 'final answer'}")
        elif k == "tool_call":
            print(f"  {el}    > {e['tool']}({e['args'][:90]})")
        elif k == "tool_result":
            print(f"  {el}      {'ok ' if e['ok'] else 'ERR'} {e['preview'][:110]}")
        elif k in ("compact", "stuck_nudge", "llm_retry"):
            print(f"  {el}  [{k}] {e}")
    return show


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m archforge.agent")
    ap.add_argument("--task", default=DEMO_TASK)
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--thinking", action="store_true", help="enable DeepSeek thinking mode (costs more)")
    ap.add_argument("--max-turns", type=int, default=20)
    a = ap.parse_args(argv)

    ws = a.workspace or os.path.join("runs", "demo-" + time.strftime("%Y%m%d-%H%M%S"))
    s = config.load_settings()
    if not s.has_key():
        print("No API key: set DEEPSEEK_API_KEY.")
        return 1
    events = EventLog(os.path.join(ws, ".archforge", "events.jsonl"))
    t0 = time.time()
    events.subscribe(_printer(t0))
    llm = LLMClient(s, events)
    sandbox = Sandbox(ws)
    ctx = ToolContext(sandbox, on_event=lambda k, d: events.emit(k, **d))
    agent = AgentLoop(llm, ToolBox(ctx), build_system_prompt(), role="demo", max_turns=a.max_turns,
                      thinking=a.thinking)

    print(f"ArchForge agent demo  (workspace: {os.path.abspath(ws)})\n")
    res = agent.run(a.task)
    m = llm.meter
    print(f"\n  Status     : {res.status} after {res.turns} turns, {res.tool_calls} tool calls "
          f"({res.failed_calls} failed/denied" + (", fed back to the model as text)" if res.failed_calls else ")"))
    print(f"  Files      : {', '.join(res.files_written) or '-'}")
    print(f"  Cost       : CNY {m.spent_cny:.4f} (= ${m.spent_cny / s.usd_to_cny:.4f}), "
          f"cache hit rate {m.usage.hit_rate:.0%}, {time.time() - t0:.0f}s")
    print(f"  Event log  : {os.path.join(ws, '.archforge', 'events.jsonl')}")
    print(f"\n  Final report from the agent:\n  " + (res.final_text or "").replace("\n", "\n  "))
    return 0 if res.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
