"""Human-readable reports: lint_report.md and assumptions.md."""

from __future__ import annotations

from .engine import Finding

ICON = {"error": "ERROR", "warning": "WARN", "info": "INFO"}


def lint_markdown(findings: list[Finding], status: list[dict], ir: dict) -> str:
    counts = {s: sum(1 for f in findings if f.severity == s) for s in ICON}
    lines = [
        f"# Spec Lint Report: {ir['system'].get('name') or 'system'}",
        "",
        f"Sources: " + ", ".join(f"`{s['file']}` (sha256 {s['sha256_16']})" for s in ir["meta"]["sources"]),
        "",
        f"**{len(findings)} findings**: {counts['error']} errors, {counts['warning']} warnings, {counts['info']} info. "
        f"**{sum(1 for f in findings if f.fix)}** are auto-resolved (see `assumptions.md`).",
        "",
        "## Rules checked",
        "",
        "| Rule | Check | Result |",
        "|---|---|---|",
    ]
    lines += [f"| {s['rule']} | {s['name']} | {s['status']}" + (f" ({s['findings']})" if s['findings'] else "") + " |"
              for s in status]
    lines += ["", "## Findings", ""]
    for f in findings:
        lines += [
            f"### {f.id} [{ICON[f.severity]}] {f.title}",
            f"*Rule {f.rule}*",
            "",
            f"**Problem.** {f.detail}",
            "",
            f"**Evidence.** " + ", ".join(f"`{e}`" for e in f.evidence if e),
            "",
            f"**Resolution.** {f.resolution}",
            "",
        ]
    return "\n".join(lines)


def assumptions_markdown(resolved: dict, findings: list[Finding]) -> str:
    by_id = {f.id: f for f in findings}
    lines = [
        "# Assumptions and Decisions",
        "",
        "Everything the generated project does that the spec does NOT literally say is listed here, "
        "with the lint finding that forced the decision. Raw spec facts are in `ir.raw.json`; "
        "the version the code is generated from is `ir.resolved.json`.",
        "",
        "## Task constraints (from the evaluator)",
        "",
        "| ID | Constraint | Source | Realised by |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c['id']} | {c['text']} | {c['source']} | {c['realised_by']} |" for c in resolved["constraints"]]
    lines += ["", "## Decisions from Spec Lint", ""]
    grouped: dict[str, list[str]] = {}
    for r in resolved["resolutions"]:
        grouped.setdefault(r["finding"], []).append(r["change"])
    for i, (fid, changes) in enumerate(grouped.items(), 1):
        f = by_id[fid]
        lines += [f"**A-{i:02d}** ({fid}, {f.rule}) {f.title}", "",
                  f"- Decision: {f.resolution}"] + [f"- IR change: `{c}`" for c in changes] + [""]
    no_fix = [f for f in findings if not f.fix]
    if no_fix:
        lines += ["## Noted, no change needed", ""]
        lines += [f"- {f.id} ({f.rule}) {f.title}. {f.resolution}" for f in no_fix]
    inferred = [r for r in resolved["requirements"] if r.get("origin") == "inferred"]
    lines += ["", "## Requirement set used for generation", "",
              "| ID | Text | Origin |", "|---|---|---|"]
    lines += [f"| {r['id']} | {r['text']} | {r.get('origin', 'spec')} |" for r in resolved["requirements"]]
    lines += ["", f"{len(inferred)} of {len(resolved['requirements'])} requirements are inferred."]
    return "\n".join(lines)
