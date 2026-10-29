"""GUI smoke test (offscreen): the window builds and reacts to pipeline events. No API, no network."""
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_window_builds_and_handles_events(tmp_path):
    from PySide6.QtWidgets import QApplication
    from archforge.gui.app import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.current_out = str(tmp_path)
    w.t0 = 1.0
    w.on_event({"kind": "phase_start", "phase": "plan"})
    w.on_event({"kind": "phase_end", "phase": "plan", "ok": True, "seconds": 3, "cost_cny": 0.1})
    w.on_event({"kind": "tests", "after": "code", "summary": "5/6 tests passed", "passed": 5, "total": 6})
    w.on_event({"kind": "llm_call", "tokens": {"cache_hit": 90, "cache_miss": 10, "output": 5, "reasoning": 0},
                "spent_cny": 3.55, "budget_cny": 7.1, "cost_cny": 0.01, "role": "x"})
    assert w.kpi_tests[1].text() == "5/6"
    assert w.kpi_cache[1].text() == "90%"
    assert w.cost_bar.value() == 500
    assert "Plan" in w.stepper.chips["plan"].text()
    w.on_finished({"status": "done", "out": str(tmp_path), "tests": "6/6 tests passed", "cost_cny": 1.0,
                   "cost_usd": 0.14, "calls": 9, "hit": 0.9, "notes": [], "tamper": [], "conformance": {},
                   "review": "approve",
                   "matrix": [{"id": "FR-1", "origin": "spec", "text": "Play", "code": ["src/a.js"], "tests": ["t"],
                               "passed": 1, "failed": 0, "status": "PASS"}]})
    assert w.trace.rowCount() == 1 and w.run_btn.isEnabled()
    w.close()
    w.deleteLater()
    app.processEvents()
