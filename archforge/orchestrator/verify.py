"""Verification: install dependencies, run the test suite, parse the results.

Jest is run with --json so results are machine-readable: every test's name,
status and failure message. The orchestrator uses this to (a) decide whether
to repair, (b) give the repair agent ONLY the relevant failures, and
(c) build the traceability matrix.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from ..agent.sandbox import Sandbox

RESULTS = ".archforge/jest-results.json"


@dataclass
class TestReport:
    ran: bool
    total: int = 0
    passed: int = 0
    failed: int = 0
    suites_failed: list = field(default_factory=list)     # suites that crashed before running tests
    tests: list = field(default_factory=list)             # [{name, file, status, message}]
    raw_output: str = ""

    @property
    def all_passed(self) -> bool:
        return self.ran and self.total > 0 and self.failed == 0 and not self.suites_failed

    def summary(self) -> str:
        if not self.ran:
            return "tests did not run"
        s = f"{self.passed}/{self.total} tests passed"
        if self.suites_failed:
            s += f", {len(self.suites_failed)} test file(s) crashed"
        return s

    def failure_digest(self, limit: int = 7000) -> str:
        """Compact list of failures for the repair agent."""
        parts = []
        for s in self.suites_failed:
            parts.append(f"TEST FILE CRASHED: {s['file']}\n{_clean(s['message'])[:1200]}")
        for t in self.tests:
            if t["status"] == "failed":
                parts.append(f"FAILED: {t['name']}  ({t['file']})\n{_clean(t['message'])[:900]}")
        text = "\n\n".join(parts)
        return text[:limit] + ("\n[... more failures omitted ...]" if len(text) > limit else "")


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _clean(msg: str) -> str:
    msg = _ANSI.sub("", msg or "")
    lines = [l for l in msg.splitlines() if "node_modules" not in l]   # drop library stack frames
    return "\n".join(lines).strip()


def npm_install(sb: Sandbox, timeout: int = 900) -> tuple[bool, str]:
    res = sb.run("npm install --no-audit --no-fund", timeout=timeout)
    return res.exit_code == 0, res.render()


def parse_jest(path: str, root: str) -> TestReport:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rep = TestReport(ran=True)
    for suite in data.get("testResults", []):
        file = os.path.relpath(suite.get("name", ""), root).replace("\\", "/")
        asserts = suite.get("assertionResults", [])
        if suite.get("status") == "failed" and not asserts:
            rep.suites_failed.append({"file": file, "message": suite.get("message", "")})
        for a in asserts:
            status = a.get("status")
            rep.tests.append({"name": a.get("fullName") or a.get("title"), "file": file, "status": status,
                              "message": "\n".join(a.get("failureMessages") or [])})
    rep.total = len(rep.tests)
    rep.passed = sum(t["status"] == "passed" for t in rep.tests)
    rep.failed = sum(t["status"] == "failed" for t in rep.tests)
    return rep


def run_tests(sb: Sandbox, timeout: int = 300) -> TestReport:
    out = os.path.join(sb.root, RESULTS)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    res = sb.run(f"npx jest --json --outputFile={RESULTS} --runInBand --forceExit", timeout=timeout)
    if not os.path.exists(out):
        return TestReport(ran=False, raw_output=res.render())
    rep = parse_jest(out, sb.root)
    rep.raw_output = res.output[-3000:]
    return rep
