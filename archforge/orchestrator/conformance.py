"""Plan conformance: does the generated code match the Architect's plan? (code, no LLM)

After the coders finish:
  missing    planned modules that do not exist
  unplanned  files that exist but were never planned
  scratch    unplanned files that look like leftovers (scratch/tmp/debug/probe...) AND are not
             referenced by any other file -> deleted, and the deletion is recorded

Missing modules are reported to the repair phase; unplanned-but-used files (e.g. the UI
coder naming public/app.js instead of public/renderer.js) are reported, not deleted.
"""

from __future__ import annotations

import os
import re

CODE_DIRS = ("src", "electron", "public")
SCRATCH = re.compile(r"(?i)(scratch|tmp|temp|debug|probe|check|try|test-?run|playground)")


def _files(root: str) -> list[str]:
    out = []
    for top in CODE_DIRS:
        for d, dirs, files in os.walk(os.path.join(root, top)):
            dirs[:] = [x for x in dirs if x != "node_modules"]
            out += [os.path.relpath(os.path.join(d, f), root).replace("\\", "/") for f in files]
    return sorted(out)


def _referenced(root: str, rel: str, files: list[str]) -> bool:
    stem = os.path.splitext(os.path.basename(rel))[0]
    for other in files:
        if other == rel:
            continue
        try:
            with open(os.path.join(root, other), encoding="utf-8", errors="ignore") as f:
                if re.search(rf"[\"'/]{re.escape(stem)}(\.js)?[\"']", f.read()):
                    return True
        except OSError:
            continue
    return False


def check(root: str, plan: dict, delete_scratch: bool = True) -> dict:
    planned = {m["path"] for m in plan.get("modules", [])}
    files = _files(root)
    missing = sorted(p for p in planned if not os.path.exists(os.path.join(root, p)))
    unplanned = [f for f in files if f not in planned]
    removed, kept = [], []
    for f in unplanned:
        if SCRATCH.search(os.path.basename(f)) and not _referenced(root, f, files):
            if delete_scratch:
                os.remove(os.path.join(root, f))
            removed.append(f)
        else:
            kept.append(f)
    total = len(planned)
    return {"planned": total, "present": total - len(missing), "missing": missing,
            "unplanned_kept": kept, "scratch_removed": removed,
            "score": round((total - len(missing)) / total, 3) if total else 1.0}


def markdown(rep: dict) -> str:
    L = ["# Plan conformance", "",
         f"{rep['present']}/{rep['planned']} planned modules present ({rep['score']:.0%}).", ""]
    for title, key in (("Missing planned modules", "missing"), ("Unplanned files (kept, in use)", "unplanned_kept"),
                       ("Leftover scratch files removed", "scratch_removed")):
        L += [f"## {title}", ""] + ([f"- `{x}`" for x in rep[key]] or ["- none"]) + [""]
    return "\n".join(L)
