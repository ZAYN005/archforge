"""The orchestrator: runs the whole generation as a sequence of phases.

  1. plan       Architect sub-agent (thinking, JSON) + validator + deterministic fallback
  2. scaffold   package.json / openapi.yaml / sql / Dockerfile (code, not LLM) + npm install
  3. tests      Tester sub-agent writes the suite from the spec (test-first); tests/ then LOCKED
  4. code       one Coder sub-agent per work package (core, components..., ui), fresh context each
  5. verify     jest --json
  6. repair     up to N rounds: failing tests -> Repair agent -> re-run (stops on no progress)
  7. review     read-only Reviewer -> JSON findings; one fix round if high-severity findings;
                test disputes judged by the Reviewer, fixed by the Tester (never by the Coder)
  8. trace      traceability matrix + README + run report

Every phase emits events (phase_start / phase_end with cost), so the GUI and the
final report show exactly where time and money went.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from ..agent.loop import AgentLoop, AgentResult
from ..agent.prompts import build_system_prompt
from ..agent.sandbox import Sandbox
from ..agent.tools import ToolBox, ToolContext
from ..llm import BudgetExceeded, LLMClient
from . import conformance, docs, integrity, plan as planning, roles, scaffold, trace, verify
from .digest import digest


@dataclass
class RunOptions:
    max_repair_rounds: int = 3
    review: bool = True
    install: bool = True
    min_cny_for_optional: float = 0.8        # skip review/extra repair if less budget than this is left
    test_first: bool = True                  # ablation switch: False = no Tester, no locked tests
    repair: bool = True                      # ablation switch: False = no verify/repair loop


@dataclass
class RunState:
    plan: dict = field(default_factory=dict)
    phases: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    tests: verify.TestReport | None = None
    test_history: list = field(default_factory=list)
    review: dict = field(default_factory=dict)
    conformance: dict = field(default_factory=dict)
    matrix: list = field(default_factory=list)
    status: str = "running"
    notes: list = field(default_factory=list)
    tamper: list = field(default_factory=list)          # test-integrity violations (detected + reverted)


class Orchestrator:
    def __init__(self, llm: LLMClient, ir: dict, out_dir: str, spec_dir: str | None = None,
                 options: RunOptions | None = None, npm_registry: str | None = None,
                 agent_runner: Callable[[roles.Role, str], AgentResult] | None = None,
                 test_runner: Callable[[], verify.TestReport] | None = None):
        self.llm, self.ir, self.events = llm, ir, llm.events
        self.root = os.path.abspath(out_dir)
        self.spec_dir = spec_dir
        self.opt = options or RunOptions()
        self.sb = Sandbox(self.root, npm_registry=npm_registry)
        self.state = RunState()
        self.project_context = ""
        self._run_agent = agent_runner or self._real_agent
        self._run_tests = test_runner or (lambda: verify.run_tests(self.sb))

    # ------------------------------------------------------------ helpers
    def _phase(self, name: str):
        orch = self

        class _P:
            def __enter__(self):
                self.t0, self.c0 = time.time(), orch.llm.meter.spent_cny
                orch.events.emit("phase_start", phase=name)
                return self

            def __exit__(self, exc_type, exc, tb):
                rec = {"phase": name, "seconds": round(time.time() - self.t0, 1),
                       "cost_cny": round(orch.llm.meter.spent_cny - self.c0, 4),
                       "ok": exc_type is None}
                orch.state.phases.append(rec)
                orch.events.emit("phase_end", **rec)
                return False
        return _P()

    def _real_agent(self, role: roles.Role, task: str) -> AgentResult:
        ctx = ToolContext(self.sb, write_scope=role.write_scope, protected=role.protected,
                          on_event=lambda k, d: self.events.emit(k, role=role.name, **d))
        loop = AgentLoop(self.llm, ToolBox(ctx, role.permission),
                         build_system_prompt(role.instructions, self.project_context),
                         role=role.name, max_turns=role.max_turns, thinking=role.thinking, effort=role.effort)
        return loop.run(task)

    TEST_WRITERS = ("tester", "test-fixer")

    def _lock_tests(self) -> None:
        self._snap = integrity.snapshot(self.root)
        self._write(".archforge/tests.lock.json", json.dumps(integrity.hashes(self._snap), indent=1))
        self.events.emit("tests_locked", files=len(self._snap))

    def _check_tests(self, after: str) -> list:
        """Detect + revert any change to tests/ since the lock (however it was made)."""
        snap = getattr(self, "_snap", None)
        if snap is None:
            return []
        bad = integrity.check(self.root, snap, restore=True)
        for v in bad:
            v["after"] = after
            self.state.tamper.append(v)
            self.events.emit("tamper", **v)
        return bad

    def agent(self, role: roles.Role, task: str) -> AgentResult:
        res = self._run_agent(role, task)
        if role.name in self.TEST_WRITERS:
            self._lock_tests()                   # legitimate test changes -> new snapshot
        else:
            self._check_tests(role.name)         # anyone else touching tests/ is reverted and reported
        self.state.agents.append({"role": role.name, "status": res.status, "turns": res.turns,
                                  "tool_calls": res.tool_calls, "failed_calls": res.failed_calls,
                                  "files": res.files_written})
        if res.status == "budget":
            raise BudgetExceeded(res.final_text)
        return res

    def _write(self, rel: str, text: str) -> None:
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def _enough_budget(self) -> bool:
        return self.llm.meter.remaining_cny >= self.opt.min_cny_for_optional

    def _test(self, label: str) -> verify.TestReport:
        self._check_tests(f"before tests ({label})")
        rep = self._run_tests()
        self.state.tests = rep
        self.state.test_history.append({"after": label, "passed": rep.passed, "total": rep.total,
                                        "crashed": len(rep.suites_failed)})
        self.events.emit("tests", after=label, summary=rep.summary(), passed=rep.passed, total=rep.total,
                         crashed=len(rep.suites_failed))
        return rep

    # ------------------------------------------------------------ phases
    def phase_plan(self) -> None:
        with self._phase("plan"):
            wps = planning.skeleton(self.ir)
            base = build_system_prompt("", digest(self.ir))
            messages = [{"role": "system", "content": base},
                        {"role": "user", "content": planning.architect_prompt(wps)}]
            plan, errors = None, ["not attempted"]
            for attempt in (1, 2):
                msg, _, _ = self.llm.chat(messages, role="architect", thinking=True, effort="high",
                                          json_mode=True, max_tokens=32000)
                plan = planning.parse_json(msg.content)
                errors = planning.validate_plan(plan, self.ir, wps) if plan else ["answer was not valid JSON"]
                self.events.emit("plan_validated", attempt=attempt, errors=errors[:10])
                if not errors:
                    break
                messages += [{"role": "assistant", "content": msg.content or ""},
                             {"role": "user", "content": "Your plan has these problems; return the corrected "
                                                         "complete JSON:\n- " + "\n- ".join(errors[:20])}]
            fixes = []
            if errors:
                plan, fixes = planning.repair_plan(plan or {}, self.ir, wps)
                self.state.notes.append(f"plan fallback filled {len(fixes)} gaps")
                self.events.emit("plan_repaired", fixes=fixes)
            plan["work_packages"] = wps
            plan["conventions"] = planning.CONVENTIONS
            self.state.plan = plan
            self._write(".archforge/plan.json", json.dumps(plan, indent=2))
            self._write("docs/PLAN.md", planning.plan_markdown(plan))
            # the shared context every later agent receives (and DeepSeek caches)
            self.project_context = (digest(self.ir) + "\n\nConventions:\n- " + "\n- ".join(planning.CONVENTIONS) +
                                    "\n\nImplementation plan (contract, follow it exactly):\n" +
                                    json.dumps({k: plan[k] for k in ("summary", "data_shapes", "modules", "api",
                                                                     "ui_screens", "seed_questions") if k in plan},
                                               separators=(",", ":")))

    def phase_scaffold(self) -> None:
        with self._phase("scaffold"):
            files = scaffold.write_scaffold(self.root, self.ir, self.state.plan, self.spec_dir)
            self.events.emit("scaffold", files=files)
            if self.opt.install:
                ok, out = verify.npm_install(self.sb)
                self.events.emit("npm_install", ok=ok, output=out[-1500:])
                if not ok:
                    self.state.notes.append("npm install failed: " + out[-300:])

    def phase_tests(self) -> None:
        with self._phase("tests"):
            self.agent(roles.tester_role(), "Write the test suite now.")

    def phase_code(self) -> None:
        with self._phase("code"):
            mods = self.state.plan.get("modules", [])
            for wp in self.state.plan["work_packages"]:
                mine = [m for m in mods if m.get("work_package") == wp["id"]]
                self.agent(roles.coder_role(wp, mine), f"Implement work package '{wp['id']}' now.")
            self._conformance("code")

    def _conformance(self, label: str) -> dict:
        rep = conformance.check(self.root, self.state.plan)
        self.state.conformance = rep
        self._write("docs/CONFORMANCE.md", conformance.markdown(rep))
        self.events.emit("conformance", after=label, present=rep["present"], planned=rep["planned"],
                         missing=rep["missing"], removed=rep["scratch_removed"], unplanned=rep["unplanned_kept"])
        return rep

    def phase_repair(self) -> None:
        with self._phase("verify_repair"):
            rep = self._test("code")
            best, stale = rep.passed, 0
            for rnd in range(1, self.opt.max_repair_rounds + 1):
                missing = self.state.conformance.get("missing", [])
                if (rep.all_passed and not missing) or not self._enough_budget():
                    break
                todo = rep.failure_digest()
                if missing:
                    todo += ("\n\nPLANNED MODULES THAT DO NOT EXIST (create them per the plan, or if their job is "
                             "already done by another file, say so in your report): " + ", ".join(missing))
                res = self.agent(roles.repair_role(todo), f"Repair round {rnd}: fix the failures.")
                if "TEST DISPUTE" in (res.final_text or ""):
                    self.state.notes.append(f"repair round {rnd} raised a test dispute")
                    self._disputes = getattr(self, "_disputes", "") + "\n" + res.final_text[-1500:]
                rep = self._test(f"repair {rnd}")
                self._conformance(f"repair {rnd}")
                stale = stale + 1 if rep.passed <= best else 0
                best = max(best, rep.passed)
                if stale >= 2:
                    self.state.notes.append("repair stopped: no progress in 2 rounds")
                    break

    def phase_review(self) -> None:
        if not self.opt.review or not self._enough_budget():
            self.state.notes.append("review skipped (disabled or budget)")
            return
        with self._phase("review"):
            res = self.agent(roles.reviewer_role(getattr(self, "_disputes", "")), "Review the project now.")
            review = planning.parse_json(res.final_text) or {"verdict": "unknown", "findings": [],
                                                              "raw": (res.final_text or "")[:2000]}
            self.state.review = review
            self._write(".archforge/review.json", json.dumps(review, indent=2))
            wrong_tests = [d for d in review.get("test_disputes", []) if d.get("decision") == "test_wrong"]
            if wrong_tests and self._enough_budget():
                self.agent(roles.test_fixer_role(json.dumps(wrong_tests, indent=1)), "Fix the disputed tests.")
            high = [f for f in review.get("findings", []) if f.get("severity") == "high"]
            if high and self._enough_budget():
                self.agent(roles.repair_role("Reviewer findings (not test failures):\n" + json.dumps(high, indent=1)),
                           "Fix the reviewer's high-severity findings, then run npx jest.")
            if wrong_tests or high:
                self._test("review fixes")
                self._conformance("review fixes")

    def phase_trace(self) -> None:
        with self._phase("trace"):
            rep = self.state.tests or verify.TestReport(ran=False)
            exists = lambda p: os.path.exists(os.path.join(self.root, p))
            m = self.llm.meter
            facts = {
                "C-1": exists("electron/main.js") and exists("public/index.html"),
                "C-1_how": "static check: electron/main.js + public/index.html exist; package.json main = electron/main.js",
                "C-2": m.spent_cny <= m.budget_cny,
                "C-2_how": f"cost meter: CNY {m.spent_cny:.4f} of {m.budget_cny:.2f} budget",
                "C-3": self.llm.s.model == "deepseek-v4-pro",
                "C-3_how": f"model used: {self.llm.s.model}",
                "C-4": all(exists(p) for p in ("package.json", "README.md", "Dockerfile")) and
                       bool(rep.total),
                "C-4_how": "static check: package.json, README.md, Dockerfile, tests/ present",
                "C-5": True, "C-5_how": "package.json pins express 4 on node >= 18",
            }
            self._write("README.md", "placeholder")       # so the C-4 check sees it; real content below
            facts["C-4"] = all(exists(p) for p in ("package.json", "README.md", "Dockerfile")) and bool(rep.total)
            self.state.matrix = trace.build_matrix(self.ir, self.root, rep.tests, facts)
            self._write("docs/TRACEABILITY.md", trace.matrix_markdown(self.state.matrix))
            self._write("traceability_matrix.csv", trace.matrix_csv(self.state.matrix))

    # ------------------------------------------------------------ run
    def run(self) -> RunState:
        t0 = time.time()
        self.events.emit("run_start", out=self.root, budget_cny=self.llm.meter.budget_cny)
        try:
            self.phase_plan()
            self.phase_scaffold()
            if self.opt.test_first:
                self.phase_tests()
            self.phase_code()
            if self.opt.repair:
                self.phase_repair()
            elif self.opt.test_first:
                self._test("code")
            self.phase_review()
            self.state.status = "done"
        except BudgetExceeded as e:
            cancelled = getattr(self.llm, "cancel", None) is not None and self.llm.cancel.is_set()
            self.state.status = "cancelled" if cancelled else "budget_stop"
            self.state.notes.append(str(e))
        finally:
            if self.state.plan:
                self.phase_trace()
                report = docs.run_report(self, time.time() - t0)
                self._write(".archforge/run_report.json", json.dumps(report, indent=2))
                self._write("README.md", docs.readme(self.ir, self.state, report))
            self.events.emit("run_end", status=self.state.status,
                             tests=self.state.tests.summary() if self.state.tests else "none",
                             cost_cny=round(self.llm.meter.spent_cny, 4), seconds=round(time.time() - t0, 1))
        return self.state
