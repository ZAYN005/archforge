"""Phase 5+6 tests: plan validation, sub-agent isolation, jest parsing, traceability, and the
full orchestrator flow driven by fake agents (no API cost, no npm)."""

import json
import os
from types import SimpleNamespace as NS

import pytest

from archforge import config
from archforge.agent.loop import AgentResult
from archforge.agent.sandbox import Sandbox
from archforge.agent.tools import ToolBox, ToolContext
from archforge.events import EventLog
from archforge.llm import LLMClient
from archforge.orchestrator import Orchestrator, RunOptions
from archforge.orchestrator import plan as P
from archforge.orchestrator import trace, verify
from archforge.orchestrator.digest import digest, endpoint_reqs
from archforge.spec.__main__ import run as run_spec

ROOT = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="module")
def ir(tmp_path_factory):
    out = tmp_path_factory.mktemp("spec")
    return run_spec(os.path.join(ROOT, "inputs", "Architecture_Documentation.md"),
                    os.path.join(ROOT, "inputs", "Architecture_View.md"), str(out))["resolved"]


# ------------------------------------------------------------------ digest / endpoint mapping
def test_endpoint_requirements(ir):
    m = endpoint_reqs(ir)
    assert m["GET /play"] == ["FR-1"]
    assert m["GET /games/{gameId}/score"] == ["FR-2"]
    assert set(m["PUT /admin/questions"]) == {"FR-3", "ASR-2"}
    assert m["GET /help"] == ["FR-4"]
    d = digest(ir)
    assert "POST /games/{gameId}/answers" in d and "FR-5" in d and "Redis" in d   # Redis listed as out of scope


# ------------------------------------------------------------------ plan validation
def test_validator_catches_gaps(ir):
    wps = P.skeleton(ir)
    bad = {"summary": "x", "api": [], "modules": [
        {"path": "src/components/game/x.js", "work_package": "question", "reqs": ["FR-1"]}]}
    errs = P.validate_plan(bad, ir, wps)
    assert any("missing endpoint GET /play" in e for e in errs)
    assert any("outside scope" in e for e in errs)
    assert any("FR-2" in e for e in errs)


def test_fallback_always_produces_a_valid_plan(ir):
    wps = P.skeleton(ir)
    plan, fixes = P.repair_plan({}, ir, wps)
    assert fixes and P.validate_plan(plan, ir, wps) == []


def test_parse_json_tolerates_fences():
    assert P.parse_json('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert P.parse_json("no json") is None


# ------------------------------------------------------------------ sub-agent isolation
def test_coder_cannot_touch_tests_or_other_packages(tmp_path):
    sb = Sandbox(str(tmp_path))
    coder = ToolBox(ToolContext(sb, write_scope=["src/components/game/*"], protected=["tests/*"]))
    ok, msg = coder.execute("write_file", json.dumps({"path": "tests/a.test.js", "content": "x"}))
    assert not ok and "protected" in msg
    ok, msg = coder.execute("write_file", json.dumps({"path": "src/components/admin/a.js", "content": "x"}))
    assert not ok and "outside your write scope" in msg
    ok, _ = coder.execute("write_file", json.dumps({"path": "src/components/game/gameService.js", "content": "x"}))
    assert ok


# ------------------------------------------------------------------ jest parsing + traceability
def test_parse_jest_and_matrix(tmp_path, ir):
    data = {"testResults": [
        {"name": str(tmp_path / "tests" / "a.test.js"), "status": "failed", "assertionResults": [
            {"fullName": "FR-1: plays", "status": "passed", "failureMessages": []},
            {"fullName": "FR-2: score", "status": "failed", "failureMessages": ["\x1b[31mExpected 1\x1b[0m"]}]},
        {"name": str(tmp_path / "tests" / "b.test.js"), "status": "failed", "message": "Cannot find module",
         "assertionResults": []}]}
    p = tmp_path / "r.json"
    p.write_text(json.dumps(data))
    rep = verify.parse_jest(str(p), str(tmp_path))
    assert (rep.total, rep.passed, rep.failed) == (2, 1, 1) and rep.suites_failed[0]["file"] == "tests/b.test.js"
    assert "\x1b" not in rep.failure_digest() and "FR-2: score" in rep.failure_digest()

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "game.js").write_text("// @req FR-1, FR-2\nfunction play(){}\n// @req FR-4\n")
    rows = {r["id"]: r for r in trace.build_matrix(ir, str(tmp_path), rep.tests, {"C-1": True, "C-1_how": "x"})}
    assert rows["FR-1"]["status"] == "PASS" and rows["FR-1"]["code"] == ["src/game.js"]
    assert rows["FR-2"]["status"] == "FAIL"
    assert rows["FR-4"]["status"] == "UNTESTED"
    assert rows["FR-3"]["status"] == "NOT_IMPLEMENTED"
    assert rows["C-1"]["status"] == "PASS"


# ------------------------------------------------------------------ full orchestrator flow
class FakeOpenAI:
    """Architect answers with a (deterministically built) valid plan."""
    def __init__(self, plan_json):
        self.plan_json = plan_json
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        msg = NS(content=self.plan_json, tool_calls=None, reasoning_content="thinking...")
        usage = NS(prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=3000, completion_tokens=2500,
                   completion_tokens_details=NS(reasoning_tokens=800))
        return NS(choices=[NS(message=msg, finish_reason="stop")], usage=usage)


def test_orchestrator_flow_with_fake_agents(tmp_path, ir):
    plan, _ = P.repair_plan({}, ir, P.skeleton(ir))
    s = config.Settings(api_key="sk-" + "t" * 40)
    llm = LLMClient(s, EventLog(str(tmp_path / "events.jsonl")), client=FakeOpenAI(json.dumps(plan)))
    calls = []

    holder = {}

    def agent_runner(role, task):
        calls.append(role.name)
        if role.name.startswith("coder-"):            # each coder creates its planned files
            wp = role.name.split("-", 1)[1]
            for m in holder["orch"].state.plan["modules"]:
                if m["work_package"] == wp:
                    f = tmp_path / "out" / m["path"]
                    f.parent.mkdir(parents=True, exist_ok=True)
                    if not f.exists():
                        f.write_text("// module\n")
        if role.name == "coder-core":
            os.makedirs(tmp_path / "out" / "src", exist_ok=True)
            (tmp_path / "out" / "src" / "app.js").write_text("// @req FR-1, FR-2, FR-3, FR-4, FR-5, ASR-1, ASR-2, NFR-1\n")
        if role.name == "coder-ui":
            os.makedirs(tmp_path / "out" / "electron", exist_ok=True)
            os.makedirs(tmp_path / "out" / "public", exist_ok=True)
            (tmp_path / "out" / "electron" / "main.js").write_text("// @req C-1\n")
            (tmp_path / "out" / "public" / "index.html").write_text("<html></html>")
        final = '{"verdict": "approve", "findings": [], "test_disputes": []}' if role.name == "reviewer" else "ok"
        return AgentResult("done", final, 3, 4, 0, [])

    names = ["FR-1: a", "FR-2: b", "FR-3: c", "FR-4: d", "FR-5: e", "ASR-1: f", "ASR-2: g", "NFR-1: h"]
    reports = iter([
        verify.TestReport(True, 8, 6, 2, tests=[{"name": n, "file": "t", "status": "failed" if i > 5 else "passed",
                                                  "message": "boom"} for i, n in enumerate(names)]),
        verify.TestReport(True, 8, 8, 0, tests=[{"name": n, "file": "t", "status": "passed", "message": ""}
                                                for n in names]),
    ])
    orch = Orchestrator(llm, ir, str(tmp_path / "out"), options=RunOptions(install=False),
                        agent_runner=agent_runner, test_runner=lambda: next(reports))
    holder["orch"] = orch
    st = orch.run()

    assert st.status == "done"
    assert calls == ["tester", "coder-core", "coder-question", "coder-game", "coder-user", "coder-admin",
                     "coder-ui", "repair", "reviewer"]                     # test-first, one repair round
    assert [p["phase"] for p in st.phases] == ["plan", "scaffold", "tests", "code", "verify_repair", "review", "trace"]
    assert [h["passed"] for h in st.test_history] == [6, 8]
    out = tmp_path / "out"
    for f in ("README.md", "openapi.yaml", "package.json", "docs/TRACEABILITY.md", "traceability_matrix.csv",
              "docs/PLAN.md", ".archforge/run_report.json", "sql/question_ddl.sql", "docs/CONFORMANCE.md"):
        assert (out / f).exists(), f
    statuses = {r["id"]: r["status"] for r in st.matrix}
    assert statuses["FR-1"] == "PASS" and statuses["C-1"] == "PASS" and statuses["C-2"] == "PASS"
    readme = (out / "README.md").read_text()
    assert "8/8 tests passed" in readme and "6/8 -> 8/8" in readme
    assert st.conformance["missing"] == [] and "Plan conformance" in readme


# ------------------------------------------------------------------ plan conformance
def test_conformance_removes_unreferenced_scratch_and_reports_gaps(tmp_path):
    from archforge.orchestrator import conformance
    (tmp_path / "src" / "game").mkdir(parents=True)
    (tmp_path / "public").mkdir()
    (tmp_path / "src" / "game" / "service.js").write_text("module.exports = {}")
    (tmp_path / "src" / "game" / "scratch.js").write_text("console.log(1)")
    (tmp_path / "public" / "index.html").write_text('<script src="app.js"></script>')
    (tmp_path / "public" / "app.js").write_text("// ui")
    (tmp_path / "public" / "debugHelpers.js").write_text("x")
    (tmp_path / "public" / "checkUtil.js").write_text("x")          # looks like scratch but IS referenced
    (tmp_path / "public" / "main.js").write_text("require('./checkUtil')")
    plan = {"modules": [{"path": "src/game/service.js"}, {"path": "src/game/routes.js"},
                        {"path": "public/index.html"}, {"path": "public/renderer.js"}]}
    rep = conformance.check(str(tmp_path), plan)
    assert rep["missing"] == ["public/renderer.js", "src/game/routes.js"]
    assert sorted(rep["scratch_removed"]) == ["public/debugHelpers.js", "src/game/scratch.js"]
    assert not (tmp_path / "src" / "game" / "scratch.js").exists()
    assert "public/checkUtil.js" in rep["unplanned_kept"] and "public/app.js" in rep["unplanned_kept"]
    assert rep["score"] == 0.5


def test_wrapup_turn_gives_final_answer_at_turn_limit(tmp_path):
    import sys
    from archforge.agent.loop import AgentLoop
    replies = [(None, [NS(id=f"c{i}", function=NS(name="list_dir", arguments="{}"))]) for i in range(2)]
    replies.append(('{"verdict": "approve"}', None))
    sent = []

    class LLM:
        events = EventLog(str(tmp_path / "e.jsonl"))
        def chat(self, messages, **kw):
            sent.append(kw.get("tools"))
            content, calls = replies.pop(0)
            return NS(content=content, tool_calls=calls, reasoning_content=None), None, 0.0

    loop = AgentLoop(LLM(), ToolBox(ToolContext(Sandbox(str(tmp_path / "ws")))), "S", max_turns=2)
    res = loop.run("review")
    assert res.status == "max_turns" and res.final_text == '{"verdict": "approve"}'
    assert sent[-1] is None                       # the wrap-up call had no tools


def test_integrity_lock_detects_and_reverts_any_change(tmp_path):
    from archforge.orchestrator import integrity
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.test.js").write_text("expect(1).toBe(1)")
    (tmp_path / "tests" / "b.test.js").write_text("expect(2).toBe(2)")
    snap = integrity.snapshot(str(tmp_path))
    (tmp_path / "tests" / "a.test.js").write_text("// weakened")        # e.g. via node script.js
    (tmp_path / "tests" / "b.test.js").unlink()
    (tmp_path / "tests" / "c.test.js").write_text("test('x', () => {})")
    bad = {v["file"]: v["change"] for v in integrity.check(str(tmp_path), snap)}
    assert bad == {"tests/a.test.js": "modified", "tests/b.test.js": "deleted", "tests/c.test.js": "added"}
    assert (tmp_path / "tests" / "a.test.js").read_text() == "expect(1).toBe(1)"
    assert (tmp_path / "tests" / "b.test.js").exists() and not (tmp_path / "tests" / "c.test.js").exists()
    assert integrity.check(str(tmp_path), snap) == []


def test_orchestrator_reverts_coder_that_edits_tests(tmp_path, ir):
    plan, _ = P.repair_plan({}, ir, P.skeleton(ir))
    s = config.Settings(api_key="sk-" + "t" * 40)
    llm = LLMClient(s, EventLog(str(tmp_path / "events.jsonl")), client=FakeOpenAI(json.dumps(plan)))
    out = tmp_path / "out"
    holder = {}

    def agent_runner(role, task):
        if role.name == "tester":
            (out / "tests").mkdir(parents=True, exist_ok=True)
            (out / "tests" / "game.test.js").write_text("test('FR-1: strict', () => expect(1).toBe(1))")
        if role.name.startswith("coder-"):
            for m in holder["o"].state.plan["modules"]:
                if m["work_package"] == role.name.split("-", 1)[1]:
                    (out / m["path"]).parent.mkdir(parents=True, exist_ok=True)
                    (out / m["path"]).write_text("//")
        if role.name == "coder-game":                      # the cheat, done "behind the tools' back"
            (out / "tests" / "game.test.js").write_text("// all checks removed")
        return AgentResult("done", '{"verdict":"approve","findings":[]}', 1, 1, 0, [])

    rep = verify.TestReport(True, 1, 1, 0, tests=[{"name": "FR-1: strict", "file": "t", "status": "passed",
                                                   "message": ""}])
    o = Orchestrator(llm, ir, str(out), options=RunOptions(install=False), agent_runner=agent_runner,
                     test_runner=lambda: rep)
    holder["o"] = o
    st = o.run()
    assert (out / "tests" / "game.test.js").read_text() == "test('FR-1: strict', () => expect(1).toBe(1))"
    assert st.tamper == [{"file": "tests/game.test.js", "change": "modified", "restored": True, "after": "coder-game"}]
    assert "detected and reverted" in (out / "README.md").read_text()
