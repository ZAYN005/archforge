"""Test integrity lock.

Problem: the write scope only guards OUR file tools. An agent can still run a script
(`node something.js`) that edits tests/ directly. So we do not rely on prevention alone:
we DETECT and UNDO.

  snapshot()  after the Tester finishes: SHA-256 + content of every file in tests/
  check()     after every agent and before every test run: compare with the snapshot;
              modified files are restored, new files removed, deleted files recreated.
              Every violation is returned so it can be logged and reported.

Only the Tester (and the test-fixer, after a Reviewer decision) may change tests; after
they run, a new snapshot is taken.
"""

from __future__ import annotations

import hashlib
import os

LOCKED_DIR = "tests"


def _walk(root: str) -> dict[str, bytes]:
    base = os.path.join(root, LOCKED_DIR)
    out = {}
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x != "node_modules"]
        for f in files:
            full = os.path.join(d, f)
            with open(full, "rb") as fh:
                out[os.path.relpath(full, root).replace("\\", "/")] = fh.read()
    return out


def snapshot(root: str) -> dict[str, dict]:
    return {rel: {"sha256": hashlib.sha256(data).hexdigest(), "data": data} for rel, data in _walk(root).items()}


def hashes(snap: dict) -> dict[str, str]:
    return {rel: v["sha256"] for rel, v in snap.items()}


def check(root: str, snap: dict, restore: bool = True) -> list[dict]:
    current = _walk(root)
    violations = []
    for rel, v in snap.items():
        if rel not in current:
            violations.append({"file": rel, "change": "deleted"})
        elif hashlib.sha256(current[rel]).hexdigest() != v["sha256"]:
            violations.append({"file": rel, "change": "modified"})
    for rel in current:
        if rel not in snap:
            violations.append({"file": rel, "change": "added"})
    if restore:
        for v in violations:
            full = os.path.join(root, v["file"])
            if v["change"] == "added":
                os.remove(full)
            else:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as fh:
                    fh.write(snap[v["file"]]["data"])
            v["restored"] = True
    return violations
