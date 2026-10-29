"""Spec Lint engine: run rules, collect findings, apply resolutions.

A RULE is a function `rule(ir) -> list[Finding]`, registered with @rule.
A FINDING says: what is wrong, how bad (error/warning/info), the evidence
(file:line), and the RESOLUTION ArchForge will apply.
A finding may carry a `fix(resolved_ir)` function. `resolve()` copies the raw
IR and applies every fix; each change is logged in `resolved["resolutions"]`
with the finding ID, so raw IR -> resolved IR is fully explainable.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Finding:
    rule: str                       # e.g. "SL-01"
    severity: str                   # "error" | "warning" | "info"
    title: str
    detail: str
    evidence: list[str]             # ["Architecture_Documentation.md:35", ...]
    resolution: str
    fix: Callable[[dict, "Finding"], None] | None = field(default=None, repr=False)
    id: str = ""                    # assigned after all rules ran: F-01, F-02, ...

    def to_dict(self) -> dict:
        return {"id": self.id, "rule": self.rule, "severity": self.severity, "title": self.title,
                "detail": self.detail, "evidence": self.evidence, "resolution": self.resolution,
                "auto_fixed": self.fix is not None}


@dataclass
class Rule:
    code: str
    name: str
    func: Callable[[dict], list[Finding]]


RULES: list[Rule] = []


def rule(code: str, name: str):
    def deco(fn):
        RULES.append(Rule(code, name, fn))
        return fn
    return deco


def record(ir: dict, finding: "Finding", change: str) -> None:
    """Log one change made to the resolved IR."""
    ir.setdefault("resolutions", []).append({"finding": finding.id, "rule": finding.rule, "change": change})


def run_lint(ir: dict) -> tuple[list[Finding], list[dict]]:
    """Returns (findings sorted by severity, per-rule status table)."""
    from . import rules  # noqa: F401  (importing registers the rules)
    findings, status = [], []
    for r in sorted(RULES, key=lambda r: r.code):
        try:
            out = r.func(ir)
            status.append({"rule": r.code, "name": r.name, "findings": len(out), "status":
                           "pass" if not out else "fail"})
            findings += out
        except Exception as e:   # a buggy rule must not kill the whole lint
            status.append({"rule": r.code, "name": r.name, "findings": 0, "status": f"crashed: {e}"})
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.rule))
    for i, f in enumerate(findings, 1):
        f.id = f"F-{i:02d}"
    return findings, status


def resolve(ir: dict, findings: list[Finding]) -> dict:
    resolved = copy.deepcopy(ir)
    resolved["resolutions"] = []
    for f in findings:
        if f.fix:
            f.fix(resolved, f)
    resolved["meta"]["stage"] = "resolved"
    resolved["lint_summary"] = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITY_ORDER}
    return resolved
