"""Compact, LLM-friendly views of the resolved IR.

The full IR is ~60 KB of JSON with source lines; agents do not need that.
`digest()` renders the parts that drive code generation as short text
(~1.5k tokens). It is the same for every agent in a run, so it sits in the
cached prompt prefix.

`endpoint_reqs()` assigns requirement IDs to endpoints deterministically.
"""

from __future__ import annotations

import re


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def endpoint_reqs(ir: dict) -> dict[str, list[str]]:
    """'GET /play' -> ['FR-1'] ... using the use cases / diagrams each endpoint was derived from."""
    reqs = ir["requirements"]
    by_text = {_norm(r["text"]): r["id"] for r in reqs}
    use_cases = {u["id"]: u["name"] for u in ir.get("use_cases", [])}
    play = next((r["id"] for r in reqs if r["type"] == "FR" and "play" in r["text"].lower()), None) or \
        next((r["id"] for r in reqs if r["type"] == "FR"), None)
    security = next((r["id"] for r in reqs if "secur" in r["text"].lower()), None)
    out = {}
    for e in ir["api"]["endpoints"]:
        ids = []
        m = re.search(r"use case (\w+)", e.get("derived_from", ""))
        if m and _norm(use_cases.get(m.group(1), "")) in by_text:
            ids.append(by_text[_norm(use_cases[m.group(1)])])
        if e["path"].startswith("/admin"):
            uc = next((by_text[k] for k in by_text if "update" in k), None)
            ids += [x for x in (uc, security) if x and x not in ids]
        if not ids and play:
            ids.append(play)
        out[f"{e['method']} {e['path']}"] = ids
    return out


def component_slug(name: str) -> str:
    return re.sub(r"Component$", "", name).lower()


def digest(ir: dict) -> str:
    L = [f"System: {ir['system'].get('name')} - {ir['system'].get('summary', '')[:400]}", ""]
    L.append("Requirements (origin: spec = in the documents, inferred = added by Spec Lint):")
    L += [f"- {r['id']} [{r.get('origin', 'spec')}]: {r['text']}" for r in ir["requirements"]]
    L.append("Task constraints:")
    L += [f"- {c['id']}: {c['text']}" for c in ir.get("constraints", [])]
    L += ["", "Components (one module folder each, src/components/<name>/):"]
    L += [f"- {c['name']} -> src/components/{component_slug(c['name'])}/ : {c['responsibility']}"
          for c in ir["components"]]
    L += ["", "Entities (class diagram, after lint fixes):"]
    for e in ir["entities"]:
        attrs = ", ".join(f"{a['name']}: {a['type']}" for a in e["attributes"])
        meths = ", ".join(f"{m['name']}({', '.join(m['params'])})" for m in e["methods"])
        L.append(f"- {e['name']} {{ {attrs} }} methods: {meths}")
    sm = ir.get("state_machine") or {}
    if sm:
        L += ["", f"Game state machine: initial {sm['initial']}, final {sm.get('final')}; transitions: " +
              "; ".join(f"{t['from']} --{t['trigger']}--> {t['to']}" for t in sm["transitions"]) +
              ". Any other transition is illegal (HTTP 409)."]
    L += ["", "REST API (exact paths; 'derived' = added from diagrams):"]
    ereq = endpoint_reqs(ir)
    for e in ir["api"]["endpoints"]:
        k = f"{e['method']} {e['path']}"
        L.append(f"- {k}  [{e.get('origin', 'spec')}] {e.get('summary', '')}  reqs: {', '.join(ereq[k])}")
    if ir.get("ui"):
        L += ["", "Desktop UI screens (in order): " + " -> ".join(s["name"] for s in ir["ui"]["screens"]) +
              f" (requirement {ir['ui']['requirement']})"]
    sel = ir.get("stack", {}).get("selected")
    if sel:
        L += ["", "Selected stack: " + "; ".join(f"{k}: {v}" for k, v in sel.items() if k != "out_of_scope"),
              "Out of scope (do NOT use): " + ", ".join(sel.get("out_of_scope", []))]
    tables = ir.get("data", {}).get("tables", [])
    seen = set()
    for t in tables:
        if t["table"] not in seen:
            seen.add(t["table"])
            L.append(f"SQL table {t['table']}(" + ", ".join(f"{c['name']} {c['type']}" for c in t["columns"]) + ")")
    return "\n".join(L)
