"""Traceability matrix: requirement -> code -> tests -> result.

Built by SCANNING the generated project, never by asking the LLM:
  code links   '@req FR-1' comments in src/, electron/, public/
  test links   requirement IDs in test names ("FR-1: answering ...") with jest pass/fail
  constraints  C-x checked by static facts (files exist, cost under budget)

Status per requirement:
  PASS            implemented and >= 1 linked test, all linked tests pass
  FAIL            at least one linked test fails
  UNTESTED        implemented (code tag) but no test names it
  NOT_IMPLEMENTED no code tag and no test
"""

from __future__ import annotations

import csv
import io
import os
import re

REQ = re.compile(r"\b((?:FR|NFR|ASR|C)-\d+)\b")
TAG = re.compile(r"@req\s+([A-Z]+-\d+(?:\s*,\s*[A-Z]+-\d+)*)")
CODE_DIRS = ("src", "electron", "public")


def scan_code(root: str) -> dict[str, list[str]]:
    links: dict[str, set] = {}
    for top in CODE_DIRS:
        for d, dirs, files in os.walk(os.path.join(root, top)):
            dirs[:] = [x for x in dirs if x != "node_modules"]
            for f in files:
                if not f.endswith((".js", ".html", ".css")):
                    continue
                full = os.path.join(d, f)
                rel = os.path.relpath(full, root).replace("\\", "/")
                with open(full, encoding="utf-8", errors="ignore") as fh:
                    for m in TAG.finditer(fh.read()):
                        for rid in re.split(r"\s*,\s*", m.group(1)):
                            links.setdefault(rid, set()).add(rel)
    return {k: sorted(v) for k, v in links.items()}


def build_matrix(ir: dict, root: str, tests: list[dict], facts: dict | None = None) -> list[dict]:
    code = scan_code(root)
    facts = facts or {}
    rows = []
    for r in ir["requirements"]:
        linked = [t for t in tests if r["id"] in REQ.findall(t["name"] or "")]
        passed = sum(t["status"] == "passed" for t in linked)
        failed = sum(t["status"] == "failed" for t in linked)
        files = code.get(r["id"], [])
        status = ("FAIL" if failed else "PASS" if linked else "UNTESTED" if files else "NOT_IMPLEMENTED")
        rows.append({"id": r["id"], "text": r["text"], "origin": r.get("origin", "spec"), "code": files,
                     "tests": [t["name"] for t in linked], "passed": passed, "failed": failed, "status": status})
    for c in ir.get("constraints", []):
        ok = facts.get(c["id"])
        rows.append({"id": c["id"], "text": c["text"], "origin": "constraint", "code": code.get(c["id"], []),
                     "tests": [facts.get(c["id"] + "_how", "")] if ok is not None else [],
                     "passed": int(bool(ok)), "failed": int(ok is False),
                     "status": "PASS" if ok else ("FAIL" if ok is False else "UNTESTED")})
    return rows


def matrix_markdown(rows: list[dict]) -> str:
    n = {s: sum(r["status"] == s for r in rows) for s in ("PASS", "FAIL", "UNTESTED", "NOT_IMPLEMENTED")}
    L = ["# Traceability Matrix", "",
         f"**{n['PASS']} PASS, {n['FAIL']} FAIL, {n['UNTESTED']} UNTESTED, {n['NOT_IMPLEMENTED']} NOT IMPLEMENTED** "
         f"({len(rows)} requirements and constraints). Built by scanning `@req` tags in the code and requirement "
         f"IDs in Jest test names, combined with the Jest results.", "",
         "| Req | Origin | Requirement | Code | Tests (passed/total) | Status |", "|---|---|---|---|---|---|"]
    for r in rows:
        code = "<br>".join(f"`{c}`" for c in r["code"][:6]) or "-"
        tests = f"{r['passed']}/{r['passed'] + r['failed']}" if r["tests"] else "-"
        L.append(f"| {r['id']} | {r['origin']} | {r['text'][:70]} | {code} | {tests} | **{r['status']}** |")
    L += ["", "## Tests per requirement", ""]
    for r in rows:
        if r["tests"]:
            L.append(f"**{r['id']}**: " + "; ".join(t for t in r["tests"][:12] if t))
    return "\n".join(L)


def matrix_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Requirement ID", "Origin", "Text", "Code files", "Tests passed", "Tests failed", "Status"])
    for r in rows:
        w.writerow([r["id"], r["origin"], r["text"], ";".join(r["code"]), r["passed"], r["failed"], r["status"]])
    return buf.getvalue()
