"""Evaluation tests: the independent probe scores a correct reference server 13/13 and catches defects."""
import os

from archforge.evaluate.__main__ import report
from archforge.evaluate.probe import run_probe

REF = os.path.join(os.path.dirname(__file__), "fixtures", "ref_server")


def test_probe_full_marks_on_reference_server():
    r = run_probe(REF)
    assert r["server_started"] and r["score"] == 13, [c for c in r["checks"] if not c["ok"]]


def test_probe_catches_unfair_option_order(monkeypatch):
    monkeypatch.setenv("SHUFFLE", "0")
    r = run_probe(REF)
    failed = [c["id"] for c in r["checks"] if not c["ok"]]
    assert failed == ["C11"]


def test_probe_handles_missing_server(tmp_path):
    r = run_probe(str(tmp_path))
    assert r["score"] == 0 and not r["server_started"]


def test_report_table(tmp_path):
    r = run_probe(REF)
    md = report([{"variant": "full", "cost_usd": 0.3, "calls": 9, "cache_hit": 0.9, "minutes": 15, "status": "done",
                  "own_tests": {"passed": 5, "total": 5, "ran": True}, "probe": r}])
    assert "| **full** | **13** |" in md and "C11" in md
