"""CLI:  python -m archforge.spec [--doc FILE] [--view FILE] [--out DIR]

Runs Phase 2 + 3 with ZERO LLM calls:
  1. parse both spec files            -> ir.raw.json       (faithful to the documents)
  2. validate the IR structure
  3. run the 21 Spec Lint rules       -> lint_report.md / lint_report.json
  4. apply resolutions + constraints  -> ir.resolved.json  (what code is generated from)
  5. write the decision log           -> assumptions.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from ..events import EventLog
from ..lint.engine import resolve, run_lint
from ..lint.report import assumptions_markdown, lint_markdown
from .constraints import TASK_CONSTRAINTS
from .ir import build_ir, validate_ir


def run(doc: str, view: str, out: str, events: EventLog | None = None) -> dict:
    os.makedirs(out, exist_ok=True)
    ev = events or EventLog(os.path.join(out, "events.jsonl"))
    t0 = time.time()

    ir = build_ir(doc, view)
    problems = validate_ir(ir)
    ev.emit("spec_parsed", requirements=len(ir["requirements"]), components=len(ir["components"]),
            diagrams=len(ir["diagrams"]), endpoints=len(ir["api"]["endpoints"]), problems=problems)

    findings, status = run_lint(ir)
    resolved = resolve(ir, findings)
    resolved["constraints"] = TASK_CONSTRAINTS
    ev.emit("spec_linted", findings=len(findings), summary=resolved["lint_summary"],
            resolutions=len(resolved["resolutions"]))

    def dump(name, obj):
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)

    dump("ir.raw.json", ir)
    dump("ir.resolved.json", resolved)
    dump("lint_report.json", {"findings": [f.to_dict() for f in findings], "rules": status})
    with open(os.path.join(out, "lint_report.md"), "w", encoding="utf-8") as f:
        f.write(lint_markdown(findings, status, ir))
    with open(os.path.join(out, "assumptions.md"), "w", encoding="utf-8") as f:
        f.write(assumptions_markdown(resolved, findings))

    return {"ir": ir, "resolved": resolved, "findings": findings, "status": status,
            "problems": problems, "seconds": round(time.time() - t0, 3)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m archforge.spec")
    ap.add_argument("--doc", default="inputs/Architecture_Documentation.md")
    ap.add_argument("--view", default="inputs/Architecture_View.md")
    ap.add_argument("--out", default="runs/spec")
    a = ap.parse_args(argv)

    res = run(a.doc, a.view, a.out)
    ir, rv, fs = res["ir"], res["resolved"], res["findings"]
    print(f"ArchForge spec pipeline ({res['seconds']}s, 0 LLM calls)\n")
    print(f"  Parsed : {len(ir['diagrams'])} diagrams, {len(ir['requirements'])} requirements, "
          f"{len(ir['components'])} components, {len(ir['entities'])} entities, "
          f"{len(ir['api']['endpoints'])} endpoint(s)")
    print(f"  IR self-check: {'OK' if not res['problems'] else res['problems']}")
    s = rv["lint_summary"]
    passed = sum(1 for x in res["status"] if x["status"] == "pass")
    print(f"  Lint   : {len(res['status'])} rules, {passed} passed | "
          f"{len(fs)} findings: {s['error']} errors, {s['warning']} warnings, {s['info']} info")
    for f in fs:
        print(f"           {f.id} {f.severity.upper():7} {f.rule}  {f.title}")
    print(f"  Resolve: {len(rv['resolutions'])} IR changes -> {len(rv['requirements'])} requirements, "
          f"{len(rv['api']['endpoints'])} endpoints, {len(rv['constraints'])} task constraints")
    print(f"\n  Output in {os.path.abspath(a.out)}:")
    for name in ("ir.raw.json", "ir.resolved.json", "lint_report.md", "lint_report.json", "assumptions.md"):
        print(f"    {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
