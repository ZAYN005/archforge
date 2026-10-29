"""Tests for Phase 2 (parsers + IR) and Phase 3 (Spec Lint). No API calls.

Two kinds of test:
  * on the REAL input files  -> the pipeline finds what it should
  * on MODIFIED copies       -> when a defect is fixed, its rule goes quiet
    (proves the rules really check the IR and are not hard-coded to this spec)
"""

import copy
import json
import os

import pytest

from archforge.lint import rules as R
from archforge.lint.engine import resolve, run_lint
from archforge.spec.__main__ import run
from archforge.spec.ir import build_ir, validate_ir
from archforge.spec.markdown import parse_markdown
from archforge.spec.plantuml import parse_plantuml_file

ROOT = os.path.dirname(os.path.dirname(__file__))
DOC = os.path.join(ROOT, "inputs", "Architecture_Documentation.md")
VIEW = os.path.join(ROOT, "inputs", "Architecture_View.md")


@pytest.fixture(scope="module")
def ir():
    return build_ir(DOC, VIEW)


# ------------------------------------------------------------- markdown parser
def test_markdown_tracks_sections_lines_tables_code():
    md = "# A\ntext\n## B\n| x | y |\n|---|---|\n| 1 | 2 |\n```sql\nCREATE TABLE t (id INT);\n```\n* item\n"
    d = parse_markdown(md, "m.md")
    table = d.find("table")[0]
    assert table.header == ["x", "y"] and table.rows == [["1", "2"]] and table.row_lines == [6]
    code = d.find("code")[0]
    assert code.lang == "sql" and code.line == 8 and code.section == ["A", "B"]
    assert d.find("bullet")[0].text == "item"


# ------------------------------------------------------------- plantuml parser
def test_plantuml_kinds_and_elements():
    ds = {d.name: d for d in parse_plantuml_file(open(VIEW, encoding="utf-8").read())}
    assert len(ds) == 13
    assert ds["UseCaseDiagram"].data["usecases"]["ViewHelp"] == "View Help"
    assert ds["StateDiagram"].data["initial"] == "Playing"
    q = ds["ClassDiagram"].data["classes"]["Question"]
    assert [a["name"] for a in q["attributes"]] == ["id", "prompt", "options"]
    assert ds["SequenceDiagram1"].data["messages"][5]["label"] == "check answer"
    assert ds["ObjectDiagram"].warnings                     # 'participant' in an object diagram


def test_state_parser_handles_final_marker():
    d = parse_plantuml_file("@startuml S\n[*] --> A\nA --> B : go()\nB --> [*]\n@enduml")[0]
    assert d.kind == "state" and d.data["final"] == ["B"] and d.data["transitions"][0]["trigger"] == "go()"


# ------------------------------------------------------------- IR
def test_ir_is_faithful(ir):
    assert ir["system"]["name"] == "Space Fractions"
    assert [r["id"] for r in ir["requirements"]] == ["ASR-1", "ASR-2", "FR-1", "NFR-1"]
    asr2 = next(r for r in ir["requirements"] if r["id"] == "ASR-2")
    assert asr2["in_traceability"] is False and asr2["text"] == "security"
    admin = next(c for c in ir["components"] if c["name"] == "AdminComponent")
    assert admin["in_text"] is False and admin["container"] == "AdminContainer"
    assert len(ir["api"]["endpoints"]) == 1                 # raw IR does NOT invent endpoints
    assert validate_ir(ir) == []


def test_every_fact_has_a_source(ir):
    for r in ir["requirements"]:
        assert r["mentions"]
    for e in ir["entities"]:
        assert ":" in e["src"]


# ------------------------------------------------------------- lint on the real spec
def test_lint_finds_known_defects(ir):
    findings, status = run_lint(ir)
    fired = {f.rule for f in findings}
    for code in ["SL-01", "SL-02", "SL-04", "SL-05", "SL-06", "SL-07", "SL-09",
                 "SL-10", "SL-11", "SL-13", "SL-14", "SL-15", "SL-16", "SL-17"]:
        assert code in fired, code
    passed = {s["rule"] for s in status if s["status"] == "pass"}
    assert {"SL-03", "SL-19"} <= passed                     # table == CSV, duplicated blocks identical
    assert not [s for s in status if s["status"].startswith("crashed")]


def test_every_finding_has_evidence_and_resolution(ir):
    for f in run_lint(ir)[0]:
        assert f.evidence and all(":" in e for e in f.evidence if e), f.id
        assert len(f.resolution) > 20, f.id


# ------------------------------------------------------------- rules go quiet when the defect is fixed
def test_slo_rule_quiet_when_math_is_right(ir):
    x = copy.deepcopy(ir)
    x["quality"]["slo"]["error_budget"]["value"] = "0.01%"
    assert R.slo_math(x) == []


def test_check_answer_rule_quiet_when_attribute_exists(ir):
    x = copy.deepcopy(ir)
    q = next(e for e in x["entities"] if e["name"] == "Question")
    q["attributes"].append({"visibility": "-", "name": "answer", "type": "string"})
    assert R.behaviour_needs_data(x) == []


def test_state_rule_quiet_with_final_state(ir):
    x = copy.deepcopy(ir)
    x["state_machine"]["final"] = ["GameOver"]
    assert R.state_machine(x) == []


def test_testing_rule_quiet_when_filled(ir):
    x = copy.deepcopy(ir)
    x["components"] = [c for c in x["components"] if c["name"] in x["testing"]["components"]]
    for c in x["testing"]["cells"]:
        c["value"] = "yes"
    assert R.testing_matrix(x) == []


def test_artifact_rule_quiet_when_names_match(ir):
    x = copy.deepcopy(ir)
    x["deliverables_declared"].append({"file": "sql/question_ddl.sql", "src": "t:1"})
    assert R.artifacts_in_deliverables(x) == []


# ------------------------------------------------------------- resolve
def test_resolve_keeps_raw_ir_untouched_and_logs_every_change(ir):
    before = json.dumps(ir, sort_keys=True)
    findings, _ = run_lint(ir)
    resolved = resolve(ir, findings)
    assert json.dumps(ir, sort_keys=True) == before          # raw IR not mutated
    ids = {f.id for f in findings}
    assert resolved["resolutions"] and all(r["finding"] in ids for r in resolved["resolutions"])
    assert {r["id"] for r in resolved["requirements"]} >= {"FR-2", "FR-3", "FR-4", "FR-5"}
    paths = {(e["method"], e["path"]) for e in resolved["api"]["endpoints"]}
    assert ("GET", "/play") in paths and ("POST", "/games/{gameId}/answers") in paths
    q = next(e for e in resolved["entities"] if e["name"] == "Question")
    assert "correctAnswer" in [a["name"] for a in q["attributes"]]
    assert "GameOver" in resolved["state_machine"]["final"]


def test_cli_writes_all_outputs(tmp_path):
    res = run(DOC, VIEW, str(tmp_path))
    for name in ("ir.raw.json", "ir.resolved.json", "lint_report.md", "lint_report.json", "assumptions.md"):
        assert (tmp_path / name).exists(), name
    assert res["problems"] == []
