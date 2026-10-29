"""Full pipeline from the command line (the GUI calls the same function).

    python -m archforge [--doc FILE] [--view FILE] [--out DIR] [--registry URL] [--no-review]

spec -> IR -> lint -> plan -> scaffold -> tests -> code -> verify/repair -> review -> traceability
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from . import config
from .events import EventLog
from .llm import LLMClient
from .orchestrator import Orchestrator, RunOptions
from .spec.__main__ import run as run_spec

NPM_MIRROR_CN = "https://registry.npmmirror.com"


def console_printer(t0: float):
    def show(e):
        k, el = e["kind"], f"{time.time() - t0:6.1f}s"
        role = e.get("role", "")
        if k == "phase_start":
            print(f"\n{el}  === {e['phase'].upper()} ===")
        elif k == "phase_end":
            print(f"{el}  --- {e['phase']} done: {e['seconds']}s, CNY {e['cost_cny']:.4f}")
        elif k == "agent_start":
            print(f"{el}  [{role}] started ({e['permission']})")
        elif k == "agent_stop":
            print(f"{el}  [{role}] {e['status']} after {e['turns']} turns")
        elif k == "tool_call":
            print(f"{el}    {role:>12} > {e['tool']}({e['args'][:80]})")
        elif k == "tool_result" and not e["ok"]:
            print(f"{el}    {role:>12}   ERR {e['preview'][:100]}")
        elif k == "llm_call":
            print(f"{el}    {role:>12}   model: CNY {e['cost_cny']:.4f}  total CNY {e['spent_cny']:.3f}"
                  f"  (cache {e['cache_hit_rate']:.0%})") if role in ("architect",) else None
        elif k == "tests":
            print(f"{el}  TESTS after {e['after']}: {e['summary']}")
        elif k == "tamper":
            print(f"{el}  !! TEST TAMPERING after {e['after']}: {e['file']} {e['change']} -> reverted")
        elif k == "conformance":
            print(f"{el}  CONFORMANCE after {e['after']}: {e['present']}/{e['planned']} planned modules; "
                  f"missing {e['missing']}; removed {e['removed']}; unplanned {e['unplanned']}")
        elif k in ("plan_validated", "plan_repaired", "npm_install", "spec_linted"):
            print(f"{el}  {k}: " + str({x: y for x, y in e.items()
                                        if x not in ("ts", "run_id", "seq", "kind", "output")})[:200])
    return show


def run_pipeline(doc: str, view: str, out: str, explicit_key: str | None = None, registry: str | None = None,
                 review: bool = True, events: EventLog | None = None, cancel=None, budget_usd: float = 1.0,
                 use_lint: bool = True, test_first: bool = True, repair: bool = True):
    s = config.load_settings(explicit_key=explicit_key, budget_usd=budget_usd)
    if not s.has_key():
        raise SystemExit("No DeepSeek API key: set DEEPSEEK_API_KEY or enter it in the GUI.")
    os.makedirs(out, exist_ok=True)
    events = events or EventLog(os.path.join(out, ".archforge", "events.jsonl"))
    spec_dir = os.path.join(out, ".archforge", "spec")
    spec = run_spec(doc, view, spec_dir, events)
    resolved = spec["resolved"]
    if not use_lint:                       # ablation: agents get the RAW IR (no fixes, no inferred items)
        import copy
        from .spec.constraints import TASK_CONSTRAINTS
        resolved = copy.deepcopy(spec["ir"])
        resolved["constraints"] = TASK_CONSTRAINTS
    llm = LLMClient(s, events, cancel=cancel)
    orch = Orchestrator(llm, resolved, out, spec_dir=spec_dir if use_lint else None,
                        options=RunOptions(review=review, test_first=test_first, repair=repair),
                        npm_registry=registry)
    state = orch.run()
    return orch, state


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m archforge")
    ap.add_argument("--doc", default="inputs/Architecture_Documentation.md")
    ap.add_argument("--view", default="inputs/Architecture_View.md")
    ap.add_argument("--out", default=os.path.join("runs", "gen-" + time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--registry", default=None, help=f"npm registry, e.g. {NPM_MIRROR_CN}")
    ap.add_argument("--cn-mirror", action="store_true", help="use the npmmirror.com registry (China)")
    ap.add_argument("--no-review", action="store_true")
    ap.add_argument("--build-game", action="store_true", help="after generation, build the game's Windows .exe")
    a = ap.parse_args(argv)

    t0 = time.time()
    events = EventLog(os.path.join(a.out, ".archforge", "events.jsonl"))
    events.subscribe(console_printer(t0))
    print(f"ArchForge -> {os.path.abspath(a.out)}")
    orch, st = run_pipeline(a.doc, a.view, a.out, registry=a.registry or (NPM_MIRROR_CN if a.cn_mirror else None),
                            review=not a.no_review, events=events)
    m = orch.llm.meter
    print(f"\n=== RESULT: {st.status} ===")
    print(f"  Tests        : {st.tests.summary() if st.tests else 'none'}")
    t = {s: sum(r['status'] == s for r in st.matrix) for s in ('PASS', 'FAIL', 'UNTESTED', 'NOT_IMPLEMENTED')}
    print(f"  Traceability : {t}")
    print(f"  Cost         : CNY {m.spent_cny:.3f} = ${m.spent_cny / orch.llm.s.usd_to_cny:.3f} "
          f"(budget ${orch.llm.s.budget_usd:.2f}), {m.calls} calls, cache hit {m.usage.hit_rate:.0%}")
    for r, u in m.by_role.items():
        print(f"     {r:>14}: in {u.cache_miss}+{u.cache_hit}c  out {u.output}")
    print(f"  Time         : {time.time() - t0:.0f}s")
    for n in st.notes:
        print(f"  note: {n}")
    print(f"  Project      : {os.path.abspath(a.out)}  (README.md, docs/TRACEABILITY.md)")
    if a.build_game and st.status == "done":
        from .orchestrator.gamebuild import build_game_exe
        print("\nBuilding the game .exe (electron-builder) ...")
        g = build_game_exe(a.out, events, china_mirror=a.cn_mirror or bool(a.registry))
        print(f"  Game .exe    : {g['exe'] if g['ok'] else 'FAILED'}  ({g['seconds']}s)")
        if not g["ok"]:
            print(g["log_tail"])
    return 0 if st.status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
