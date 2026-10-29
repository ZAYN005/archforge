"""Evaluation + ablation study.

    python -m archforge.evaluate --cn-mirror                       # all 4 variants, $0.50 cap each
    python -m archforge.evaluate --variants full,single-agent      # a subset
    python -m archforge.evaluate --probe-only DIR [DIR ...]        # score existing projects (free)

Variants (same inputs, same model, same budget cap, same sandbox):
  full          the complete ArchForge pipeline
  no-lint       Spec Lint switched off: agents get the RAW IR (1 endpoint, 4 requirements, no fixes)
  no-tests      no Tester, no locked tests, no repair loop (plan + coders + review only)
  single-agent  baseline: ONE agent with the same 7 tools reads the two documents and builds everything
                (a plain Claude-Code-style loop without spec analysis, planning or sub-agents)

Every result is scored by the SAME independent acceptance probe (13 black-box checks), plus the
project's own test results, cost and time. Output: <out>/EVALUATION.md and eval.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from .. import config
from ..agent.loop import AgentLoop
from ..agent.prompts import build_system_prompt
from ..agent.sandbox import Sandbox
from ..agent.tools import ToolBox, ToolContext
from ..events import EventLog
from ..llm import LLMClient
from ..orchestrator import verify
from .probe import CHECKS, run_probe

NPM_CN = "https://registry.npmmirror.com"
VARIANTS = {
    "full": dict(use_lint=True, test_first=True, repair=True),
    "no-lint": dict(use_lint=False, test_first=True, repair=True),
    "no-tests": dict(use_lint=True, test_first=False, repair=False),
    "single-agent": None,
}

BASELINE_TASK = """Build a complete software project from the architecture documents in spec_input/
(Architecture_Documentation.md and Architecture_View.md, the latter with PlantUML diagrams).
Requirements from the evaluator: the generated game must be a DESKTOP application (Electron), with full source,
package.json, README, tests (Jest) and a Dockerfile. Use Node.js 18+ and Express 4.
Interface needed by the evaluation harness: package.json script "server" = "node <file>" starts the REST API on
process.env.PORT (default 3000), stores data in the JSON file process.env.DATA_FILE, and protects admin routes
with the header x-admin-token equal to process.env.ADMIN_TOKEN. Run npm install and your tests before finishing."""


def run_baseline(out: str, doc: str, view: str, budget_usd: float, registry: str | None, events: EventLog):
    os.makedirs(os.path.join(out, "spec_input"), exist_ok=True)
    shutil.copy(doc, os.path.join(out, "spec_input", "Architecture_Documentation.md"))
    shutil.copy(view, os.path.join(out, "spec_input", "Architecture_View.md"))
    s = config.load_settings(budget_usd=budget_usd)
    llm = LLMClient(s, events)
    sb = Sandbox(out, npm_registry=registry, max_timeout=900)
    ctx = ToolContext(sb, on_event=lambda k, d: events.emit(k, role="single-agent", **d))
    loop = AgentLoop(llm, ToolBox(ctx), build_system_prompt(), role="single-agent", max_turns=60)
    res = loop.run(BASELINE_TASK)
    return llm, res, sb


def evaluate_project(root: str, registry: str | None) -> dict:
    """Own tests + acceptance probe for any project folder."""
    sb = Sandbox(root, npm_registry=registry, max_timeout=900)
    if os.path.exists(os.path.join(root, "package.json")) and not os.path.isdir(os.path.join(root, "node_modules")):
        verify.npm_install(sb)
    tests = verify.run_tests(sb) if os.path.exists(os.path.join(root, "package.json")) else verify.TestReport(False)
    probe = run_probe(root)
    return {"own_tests": {"passed": tests.passed, "total": tests.total, "ran": tests.ran}, "probe": probe}


def run_variant(name: str, base_out: str, doc: str, view: str, budget: float, registry: str | None) -> dict:
    out = os.path.join(base_out, name)
    os.makedirs(out, exist_ok=True)
    events = EventLog(os.path.join(out, ".archforge", "events.jsonl"))
    t0 = time.time()
    print(f"\n##### variant {name} -> {out}")
    if VARIANTS[name] is None:
        llm, res, _ = run_baseline(out, doc, view, budget, registry, events)
        status = res.status
    else:
        from ..__main__ import run_pipeline
        orch, st = run_pipeline(doc, view, out, registry=registry, events=events, budget_usd=budget,
                                **VARIANTS[name])
        llm, status = orch.llm, st.status
    gen_seconds = time.time() - t0
    m = llm.meter
    ev = evaluate_project(out, registry)
    row = {"variant": name, "status": status, "cost_usd": round(m.spent_cny / llm.s.usd_to_cny, 4),
           "calls": m.calls, "cache_hit": round(m.usage.hit_rate, 3), "minutes": round(gen_seconds / 60, 1), **ev}
    p = ev["probe"]
    print(f"  {name}: probe {p['score']}/{p['max']}, own tests {ev['own_tests']['passed']}/{ev['own_tests']['total']},"
          f" ${row['cost_usd']:.3f}, {row['minutes']} min, status {status}")
    return row


def report(rows: list[dict]) -> str:
    L = ["# ArchForge evaluation", "",
         "All variants: same two input documents, model deepseek-v4-pro, same sandbox, same per-run budget cap. "
         "Scored by an **independent acceptance probe** (13 black-box HTTP checks against the running server; "
         "it never reads the generated tests).", "",
         "| Variant | Probe (of 13) | Own tests | Cost | Minutes | LLM calls | Cache hit | Status |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        t = r["own_tests"]
        L.append(f"| **{r['variant']}** | **{r['probe']['score']}** | "
                 f"{t['passed']}/{t['total'] if t['ran'] else '-'} | "
                 f"{'$%.3f' % r['cost_usd'] if r.get('cost_usd') is not None else '-'} | {r.get('minutes', '-')} | "
                 f"{r.get('calls', '-')} | {('%d%%' % (r['cache_hit'] * 100)) if r.get('cache_hit') is not None else '-'}"
                 f" | {r.get('status', '-')} |")
    L += ["", "## Probe checks per variant", "",
          "| Check | " + " | ".join(r["variant"] for r in rows) + " |",
          "|---|" + "---|" * len(rows)]
    for cid, name in CHECKS:
        cells = []
        for r in rows:
            c = next(x for x in r["probe"]["checks"] if x["id"] == cid)
            cells.append("pass" if c["ok"] else "**fail**")
        L.append(f"| {cid} {name} | " + " | ".join(cells) + " |")
    L += ["", "## Failure details", ""]
    for r in rows:
        bad = [c for c in r["probe"]["checks"] if not c["ok"]]
        if bad:
            L.append(f"**{r['variant']}**: " + "; ".join(f"{c['id']} ({c['detail']})" for c in bad))
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m archforge.evaluate")
    ap.add_argument("--variants", default="full,no-lint,no-tests,single-agent")
    ap.add_argument("--budget", type=float, default=0.5, help="USD cap per variant")
    ap.add_argument("--doc", default="inputs/Architecture_Documentation.md")
    ap.add_argument("--view", default="inputs/Architecture_View.md")
    ap.add_argument("--out", default=os.path.join("runs", "eval-" + time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--cn-mirror", action="store_true")
    ap.add_argument("--probe-only", nargs="+", metavar="DIR", help="only score existing project folders")
    a = ap.parse_args(argv)
    registry = NPM_CN if a.cn_mirror else None
    os.makedirs(a.out, exist_ok=True)

    rows = []
    if a.probe_only:
        for d in a.probe_only:
            ev = evaluate_project(d, registry)
            rows.append({"variant": os.path.basename(os.path.normpath(d)), "cost_usd": None, **ev})
            print(f"{d}: probe {ev['probe']['score']}/13, own tests {ev['own_tests']['passed']}/"
                  f"{ev['own_tests']['total']}")
    else:
        for v in [x.strip() for x in a.variants.split(",") if x.strip()]:
            if v not in VARIANTS:
                print(f"unknown variant {v}")
                return 2
            try:
                rows.append(run_variant(v, a.out, a.doc, a.view, a.budget, registry))
            except Exception as e:                       # one failing variant must not lose the others
                print(f"  {v} crashed: {e}")
                rows.append({"variant": v, "status": f"crashed: {e}"[:80], "cost_usd": None,
                             "own_tests": {"passed": 0, "total": 0, "ran": False},
                             "probe": {"score": 0, "max": 13, "checks": [{"id": c, "name": n, "ok": False,
                                                                           "detail": "crashed"} for c, n in CHECKS]}})
            with open(os.path.join(a.out, "eval.json"), "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2)
    with open(os.path.join(a.out, "eval.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    with open(os.path.join(a.out, "EVALUATION.md"), "w", encoding="utf-8") as f:
        f.write(report(rows))
    print(f"\nReport: {os.path.abspath(os.path.join(a.out, 'EVALUATION.md'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
