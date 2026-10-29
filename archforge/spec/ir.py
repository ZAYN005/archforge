"""Build the Intermediate Representation (IR) from the two spec files.

The IR is one JSON document that answers, in a machine-readable way:
"What does the architecture say?" -- requirements, components, entities,
state machine, interactions, API, data, stack, quality targets, deliverables.

RULE: the raw IR is FAITHFUL to the documents. It does not fix anything or
invent anything; it only records. Every fact carries `src` = "file:line".
Fixes and inferences happen later, in the Spec Lint "resolve" step, which
produces a separate resolved IR where every change is tagged with the lint
finding that caused it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re

import yaml

from .markdown import MarkdownDoc, parse_markdown
from .plantuml import Diagram, parse_plantuml_file

IR_VERSION = "1.0"
REQ_ID = re.compile(r"\b((?:FR|NFR|ASR)-\d+)\b")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _fingerprint(source: str) -> str:
    """Hash of a diagram's content ignoring whitespace and notes: equal hash = duplicate diagram."""
    body = re.sub(r"(?m)^\s*note\b.*$", "", source)
    return _sha(re.sub(r"\s+", "", body))


def _stem(name: str) -> str:
    """GameComponent / GameContainer / GameServer / Game -> 'game' (used to match the same thing across views)."""
    return re.sub(r"(Component|Container|Server|Client|Service)$", "", name).lower()


def _split_list(text: str) -> list[str]:
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", text)
    return [re.sub(r"^(an?|the)\s+", "", p.strip(), flags=re.I) for p in parts if p.strip()]


# ====================================================================== documentation
def _system(doc: MarkdownDoc) -> dict:
    out: dict = {"name": "", "summary": "", "style": "", "deployment": "", "experience_flow": [],
                 "referenced_inputs": []}
    for it in doc.find("line", r"Executive Summary"):
        t = it.text
        if not out["summary"] and len(t) > 80:
            out["summary"], out["summary_src"] = t, doc.where(it)
            if m := re.search(r"The (.+?) system is", t):
                out["name"] = m.group(1)
            if m := re.search(r"consists of (.+?)\.", t):
                out["experience_flow"] = _split_list(m.group(1))
                out["experience_flow_src"] = doc.where(it)
        if m := re.match(r"Chosen architectural style:\s*(.+)", t):
            out["style"], out["style_src"] = m.group(1).strip(), doc.where(it)
        if m := re.match(r"Deployment topology:\s*(.+)", t):
            out["deployment"] = m.group(1).strip()
    for n, t in doc.grep(r"(?i)\b(requirements document|requirements doc)\b"):
        out["referenced_inputs"].append({"name": "Requirements document", "src": f"{doc.path}:{n}"})
    if m := doc.grep(r"(\d+)\s+PlantUML diagrams"):
        n, t = m[0]
        out["declared_diagram_count"] = int(re.search(r"(\d+)\s+PlantUML", t).group(1))
        out["declared_diagram_count_src"] = f"{doc.path}:{n}"
    return out


def _table_rows(item) -> list[tuple[int, dict]]:
    return [(ln, dict(zip(item.header, r))) for ln, r in zip(item.row_lines, item.rows)]


def _requirements(doc: MarkdownDoc) -> tuple[list[dict], list[dict], list[dict]]:
    reqs: dict[str, dict] = {}

    def req(rid: str) -> dict:
        return reqs.setdefault(rid, {
            "id": rid, "type": rid.split("-")[0], "text": "", "origin": "spec",
            "in_traceability": False, "diagrams": [], "components": [], "artifacts": [],
            "test_types": [], "mentions": []})

    # every mention of an ID anywhere in the document
    for n, t in doc.grep(REQ_ID.pattern):
        for rid in REQ_ID.findall(t):
            req(rid)["mentions"].append(f"{doc.path}:{n}")

    trace_rows: list[dict] = []
    qa_rows: list[dict] = []
    for tbl in doc.find("table"):
        h = [c.lower() for c in tbl.header]
        if h and h[0].startswith("requirement id"):                       # traceability matrix
            for ln, row in _table_rows(tbl):
                rid = row.get("Requirement ID", "").strip()
                r = req(rid)
                r.update(text=row.get("Short Text", ""), in_traceability=True, src=f"{doc.path}:{ln}")
                r["diagrams"] = [x.strip() for x in row.get("Diagram(s)", "").split(",") if x.strip()]
                r["components"] = [x.strip() for x in row.get("Component(s)", "").split(",") if x.strip()]
                r["artifacts"] = [x.strip() for x in row.get("Artifact filename(s)", "").split(",") if x.strip()]
                r["rationale"] = row.get("Rationale", "")
                trace_rows.append({**row, "src": f"{doc.path}:{ln}"})
        elif h and "asr/nfr id" in h[0]:                                  # QA coverage mapping
            for ln, row in _table_rows(tbl):
                cell = row.get(tbl.header[0], "")
                if m := re.match(r"(\S+)\s*\((.+)\)", cell):
                    r = req(m.group(1))
                    r["test_types"] = [x.strip() for x in row.get("Test Type", "").split(",")]
                    if not r["text"]:
                        r["text"], r["text_src"] = m.group(2), f"{doc.path}:{ln}"
                    qa_rows.append({"id": m.group(1), "theme": m.group(2), "src": f"{doc.path}:{ln}"})

    # the traceability CSV inside "Deliverables" is a second copy; keep it for cross-checking
    csv_rows = []
    for code in doc.find("code"):
        if code.lang == "csv":
            for i, row in enumerate(csv.DictReader(io.StringIO(code.text))):
                csv_rows.append({**row, "src": f"{doc.path}:{code.line + 1 + i}"})
    return sorted(reqs.values(), key=lambda r: (r["type"], r["id"])), trace_rows, csv_rows


def _components_text(doc: MarkdownDoc) -> list[dict]:
    comps = []
    for b in doc.find("bullet", r"Architecture Overview"):
        if m := re.match(r"(\w+Component)\s*:\s*(.+)", b.text):
            comps.append({"name": m.group(1), "responsibility": m.group(2), "src": doc.where(b)})
    return comps


def _stack(doc: MarkdownDoc) -> dict:
    options, recommended = [], []
    for b in doc.find("bullet", r"Technology options"):
        m = re.match(r"(.+?):\s*(.+?)\s*\(Justification:\s*meets\s+(\S+)\s*\((.+?)\)\)", b.text)
        if m:
            options.append({"category": m.group(1).strip(), "choice": m.group(2).strip(),
                            "justified_by": m.group(3), "justification_theme": m.group(4),
                            "component": next((s for s in b.section if s.endswith("Component")), ""),
                            "src": doc.where(b)})
    for b in doc.find("bullet", r"Recommended default stack"):
        recommended.append({"item": b.text, "src": doc.where(b)})
    return {"options": options, "recommended": recommended}


def _openapi(doc: MarkdownDoc) -> tuple[list[dict], list[dict]]:
    """Returns (endpoints from the first OpenAPI block, list of all OpenAPI blocks with parse status)."""
    endpoints, blocks = [], []
    for code in doc.find("code"):
        if code.lang in ("yml", "yaml") and re.search(r"^openapi:", code.text, re.M):
            entry = {"src": doc.where(code), "section": code.section[-1] if code.section else "",
                     "valid": True, "sha": _sha(code.text)}
            try:
                spec = yaml.safe_load(code.text)
                entry["title"] = spec.get("info", {}).get("title", "")
                for path, ops in (spec.get("paths") or {}).items():
                    for method, op in (ops or {}).items():
                        resp = (op or {}).get("responses", {})
                        ok = resp.get(200) or resp.get("200") or {}
                        schema = (ok.get("content", {}).get("application/json", {}).get("schema", {}))
                        if not blocks:      # endpoints come from the first (primary) block
                            endpoints.append({"method": method.upper(), "path": path,
                                              "summary": (op or {}).get("summary", ""),
                                              "response_schema": schema, "origin": "spec",
                                              "src": doc.where(code)})
            except yaml.YAMLError as e:
                entry.update(valid=False, error=str(e))
            blocks.append(entry)
    return endpoints, blocks


def _proto(doc: MarkdownDoc) -> list[dict]:
    out = []
    for code in doc.find("code"):
        if code.lang == "proto":
            rpcs = [{"service": s, "rpc": r, "request": a, "response": b}
                    for s, body in re.findall(r"service\s+(\w+)\s*\{(.*?)\}", code.text, re.S)
                    for r, a, b in re.findall(r"rpc\s+(\w+)\s*\((\w+)\)\s*returns\s*\((\w+)\)", body)]
            msgs = {name: re.findall(r"(\w+)\s+(\w+)\s*=\s*\d+", body)
                    for name, body in re.findall(r"message\s+(\w+)\s*\{(.*?)\}", code.text, re.S)}
            out.append({"rpcs": rpcs, "messages": {k: [{"type": t, "name": n} for t, n in v]
                                                    for k, v in msgs.items()},
                        "src": doc.where(code), "sha": _sha(code.text)})
    return out


def _sql(doc: MarkdownDoc) -> list[dict]:
    out = []
    for code in doc.find("code"):
        if code.lang == "sql":
            for name, cols in re.findall(r"CREATE TABLE\s+(\w+)\s*\((.*?)\);", code.text, re.S | re.I):
                columns = []
                for c in [c.strip() for c in cols.split(",") if c.strip()]:
                    parts = c.split()
                    columns.append({"name": parts[0], "type": parts[1] if len(parts) > 1 else "",
                                    "constraints": " ".join(parts[2:])})
                out.append({"table": name, "columns": columns, "src": doc.where(code),
                            "section": code.section[-1] if code.section else "", "sha": _sha(code.text)})
    return out


def _k8s(doc: MarkdownDoc) -> list[dict]:
    out = []
    for code in doc.find("code"):
        if code.lang in ("yml", "yaml") and re.search(r"^apiVersion:", code.text, re.M):
            entry = {"src": doc.where(code), "valid": True}
            try:
                m = yaml.safe_load(code.text)
                containers = m["spec"]["template"]["spec"]["containers"]
                entry.update(kind=m.get("kind"), name=m["metadata"]["name"],
                             replicas=m["spec"].get("replicas"),
                             images=[c.get("image") for c in containers],
                             ports=[p.get("containerPort") for c in containers for p in c.get("ports", [])])
            except Exception as e:   # noqa: BLE001 - any structural problem = invalid manifest
                entry.update(valid=False, error=str(e))
            out.append(entry)
    return out


def _quality(doc: MarkdownDoc) -> dict:
    q: dict = {"slo": {}, "risks": [], "assumptions": [], "open_questions": []}
    for b in doc.find("bullet", r"SLOs"):
        if m := re.match(r"(SLO|Error budget|RTO|RPO):\s*(.+)", b.text):
            q["slo"][m.group(1).lower().replace(" ", "_")] = {"value": m.group(2), "src": doc.where(b)}
    for tbl in doc.find("table"):
        if tbl.header and tbl.header[0].lower() == "risk":
            q["risks"] = [{"risk": r.get("Risk"), "mitigation": r.get("Mitigation"), "src": f"{doc.path}:{ln}"}
                          for ln, r in _table_rows(tbl)]
    for it in doc.find(None, r"Assumptions"):
        if it.kind in ("line", "bullet") and (m := re.match(r"(A\d+):\s*(.+)", it.text)):
            q["assumptions"].append({"id": m.group(1), "text": m.group(2), "src": doc.where(it)})
    for b in doc.find("bullet", r"Unresolved stakeholder"):
        q["open_questions"].append({"text": b.text, "src": doc.where(b)})
    return q


def _testing(doc: MarkdownDoc) -> dict:
    for tbl in doc.find("table", r"Testing Strategy"):
        cells = [(ln, row[0], tbl.header[j], row[j])
                 for ln, row in zip(tbl.row_lines, tbl.rows) for j in range(1, len(tbl.header))]
        return {"matrix_src": doc.where(tbl), "components": tbl.header[1:],
                "test_types": [r[0] for r in tbl.rows],
                "cells": [{"test_type": t, "component": c, "value": v.strip(), "src": f"{doc.path}:{ln}"}
                          for ln, t, c, v in cells]}
    return {}


def _deliverables(doc: MarkdownDoc) -> list[dict]:
    for code in doc.find("code", r"Deliverables"):
        if code.lang in ("markdown", "md", ""):
            return [{"file": f.strip(), "src": f"{doc.path}:{code.line + i}"}
                    for i, f in enumerate(code.text.splitlines()) if f.strip()]
    return []


def _review_checklist(doc: MarkdownDoc) -> list[dict]:
    return [{"text": b.text, "src": doc.where(b)} for b in doc.find("bullet", r"How to review")]


# ====================================================================== views
def _views(diagrams: list[Diagram], path: str) -> dict:
    by_kind: dict[str, list[Diagram]] = {}
    for d in diagrams:
        by_kind.setdefault(d.kind, []).append(d)

    def src(d, line=None):
        return f"{path}:{line or d.line}"

    out: dict = {"actors": [], "use_cases": [], "entities": [], "state_machine": {},
                 "activity": [], "interactions": [], "packages": {}, "component_diagram": [],
                 "deployment_nodes": [], "containers": []}

    for d in by_kind.get("usecase", []):
        for aid, label in d.data["actors"].items():
            out["actors"].append({"id": aid, "name": label, "src": src(d)})
        for uid, label in d.data["usecases"].items():
            actors = [l["actor"] for l in d.data["links"] if l["usecase"] == uid]
            out["use_cases"].append({"id": uid, "name": label, "actors": actors, "src": src(d)})
    for d in by_kind.get("class", []):
        for name, c in d.data["classes"].items():
            rels = [r for r in d.data["relations"] if name in (r["from"], r["to"])]
            out["entities"].append({"name": name, "attributes": c["attributes"], "methods": c["methods"],
                                    "relations": rels, "src": src(d, c["line"])})
    for d in by_kind.get("state", []):
        out["state_machine"] = {**d.data, "src": src(d)}
    for d in by_kind.get("activity", []):
        out["activity"] = [{**s, "src": src(d, s["line"])} for s in d.data["steps"]]
    for d in by_kind.get("sequence", []):
        out["interactions"].append({"diagram": d.name, "participants": d.data["participants"],
                                    "scenario": d.data["scenario"],
                                    "messages": [{**m, "src": src(d, m["line"])} for m in d.data["messages"]],
                                    "src": src(d)})
    for d in by_kind.get("package", []):
        out["packages"] = d.data["packages"]
    for kind, key in (("component", "component_diagram"), ("deployment", "deployment_nodes"),
                      ("container", "containers")):
        for d in by_kind.get(kind, []):
            out[key] += [{"name": e["name"], "src": src(d, e["line"])} for e in d.data["elements"]]
            out[key + "_links"] = [{"from": l["from"], "to": l["to"]} for l in d.data["links"]]
    return out


def _merge_components(text_comps: list[dict], views: dict) -> list[dict]:
    """One record per component, showing where it appears in each view."""
    names = [c["name"] for c in text_comps] + [c["name"] for c in views["component_diagram"]]
    merged: dict[str, dict] = {}
    for n in names:
        merged.setdefault(n, {"name": n, "responsibility": "", "in_text": False,
                              "in_component_diagram": False})
    for c in text_comps:
        merged[c["name"]].update(responsibility=c["responsibility"], in_text=True, text_src=c["src"])
    for c in views["component_diagram"]:
        merged[c["name"]].update(in_component_diagram=True, diagram_src=c["src"])
    for comp in merged.values():
        st = _stem(comp["name"])
        comp["package"] = next((p for p, cls in views["packages"].items()
                                if _stem(p) == st or any(_stem(c) == st for c in cls)), None)
        comp["entity"] = next((e["name"] for e in views["entities"] if _stem(e["name"]) == st), None)
        comp["deployment_node"] = next((n["name"] for n in views["deployment_nodes"]
                                        if _stem(n["name"]) == st), None)
        comp["container"] = next((n["name"] for n in views["containers"] if _stem(n["name"]) == st), None)
        comp["depends_on"] = sorted({l["to"] if l["from"] == comp["name"] else l["from"]
                                     for l in views.get("component_diagram_links", [])
                                     if comp["name"] in (l["from"], l["to"])})
    return list(merged.values())


# ====================================================================== public API
def build_ir(doc_path: str, view_path: str) -> dict:
    with open(doc_path, encoding="utf-8") as f:
        doc_text = f.read()
    with open(view_path, encoding="utf-8") as f:
        view_text = f.read()
    doc = parse_markdown(doc_text, os.path.basename(doc_path))
    vname = os.path.basename(view_path)
    diagrams = parse_plantuml_file(view_text, vname)

    reqs, trace_rows, csv_rows = _requirements(doc)
    views = _views(diagrams, vname)
    endpoints, openapi_blocks = _openapi(doc)

    return {
        "meta": {"ir_version": IR_VERSION, "generator": "archforge.spec",
                 "sources": [{"file": doc.path, "sha256_16": _sha(doc_text)},
                             {"file": vname, "sha256_16": _sha(view_text)}]},
        "system": _system(doc),
        "requirements": reqs,
        "traceability_declared": {"table": trace_rows, "csv": csv_rows},
        "components": _merge_components(_components_text(doc), views),
        "actors": views["actors"],
        "use_cases": views["use_cases"],
        "entities": views["entities"],
        "state_machine": views["state_machine"],
        "activity": views["activity"],
        "interactions": views["interactions"],
        "packages": views["packages"],
        "deployment": {"nodes": views["deployment_nodes"], "containers": views["containers"],
                       "k8s": _k8s(doc)},
        "api": {"endpoints": endpoints, "openapi_blocks": openapi_blocks, "internal": _proto(doc)},
        "data": {"tables": _sql(doc)},
        "stack": _stack(doc),
        "quality": _quality(doc),
        "testing": _testing(doc),
        "deliverables_declared": _deliverables(doc),
        "review_checklist": _review_checklist(doc),
        "diagrams": [{"name": d.name, "kind": d.kind, "view": d.view, "caption": d.caption,
                      "src": f"{vname}:{d.line}", "warnings": d.warnings,
                      "fingerprint": _fingerprint(d.source)} for d in diagrams],
    }


def validate_ir(ir: dict) -> list[str]:
    """Structural self-check of the IR. Returns a list of problems (empty = valid)."""
    problems = []
    required = ["meta", "system", "requirements", "components", "entities", "api", "diagrams"]
    problems += [f"missing top-level key: {k}" for k in required if k not in ir]
    ids = [r["id"] for r in ir.get("requirements", [])]
    problems += [f"duplicate requirement id: {i}" for i in set(ids) if ids.count(i) > 1]
    sm = ir.get("state_machine") or {}
    for t in sm.get("transitions", []):
        for end in ("from", "to"):
            if t[end] not in sm.get("states", []):
                problems.append(f"transition references unknown state {t[end]}")
    known = {e["name"] for e in ir.get("entities", [])} | {a["id"] for a in ir.get("actors", [])}
    for it in ir.get("interactions", []):
        for p in it["participants"]:
            if p not in known:
                problems.append(f"{it['diagram']}: participant '{p}' is neither an entity nor an actor")
    return problems
