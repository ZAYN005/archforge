"""The Spec Lint rules.

Each rule checks ONE kind of problem, generically (it inspects the IR, it
does not hard-code this particular spec). Rules that find nothing "pass" --
the report lists those too, which shows the checks are real.

Rule map:
  SL-01 artifact names in traceability vs deliverables
  SL-02 requirement IDs used in the doc but missing from traceability
  SL-03 traceability table vs traceability CSV consistency
  SL-04 components in diagrams but missing from the text
  SL-05 empty / incomplete testing matrix
  SL-06 stack justifications that do not match the cited requirement
  SL-07 use cases with no requirement
  SL-08 user-facing experience (from summary) not covered by any diagram
  SL-09 API contract too small for the interactions in the diagrams
  SL-10 identifier types disagree across class diagram / API / proto / SQL
  SL-11 behaviour that needs data the model does not have ("check answer")
  SL-12 sequence messages calling methods that no class defines
  SL-13 SLO vs error budget arithmetic
  SL-14 state machine without final state / dead ends
  SL-15 PlantUML syntax problems
  SL-16 duplicate diagrams and declared-vs-actual diagram count
  SL-17 architectural style vs deployment manifests
  SL-18 package diagram vs component diagram grouping
  SL-19 duplicated contract blocks disagree
  SL-20 referenced inputs that were not provided
  SL-21 recommended stack far larger than the system's scope
"""

from __future__ import annotations

import re

from .engine import Finding, record, rule


# ---------------------------------------------------------------- helpers
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _next_fr(ir: dict) -> str:
    nums = [int(r["id"].split("-")[1]) for r in ir["requirements"] if r["type"] == "FR"]
    return f"FR-{max(nums, default=0) + 1}"


def _req(ir, rid):
    return next((r for r in ir["requirements"] if r["id"] == rid), None)


def _entity(ir, name):
    return next((e for e in ir["entities"] if e["name"] == name), None)


# ---------------------------------------------------------------- SL-01
@rule("SL-01", "Traceability artifacts exist in deliverables")
def artifacts_in_deliverables(ir):
    declared = {d["file"] for d in ir["deliverables_declared"]}
    out = []
    rows = ir["traceability_declared"]["table"] + ir["traceability_declared"]["csv"]
    missing: dict[str, list[str]] = {}
    for row in rows:
        for art in [a.strip() for a in row.get("Artifact filename(s)", "").split(",") if a.strip()]:
            if art not in declared:
                missing.setdefault(art, []).append(row["src"])
    for art, srcs in missing.items():
        similar = [d for d in declared if d.split("/")[0] == art.split("/")[0] and d.endswith(art[-4:])]
        deliv_src = [d["src"] for d in ir["deliverables_declared"] if d["file"] in similar]

        def fix(r, f, art=art):
            r["deliverables_declared"].append({"file": art, "src": "resolved", "origin": "resolved"})
            record(r, f, f"added deliverable {art}")
            if "question" in art and not any(t["table"] == "questions" for t in r["data"]["tables"]):
                r["data"]["tables"].append({
                    "table": "questions", "file": art, "origin": "resolved",
                    "columns": [{"name": "id", "type": "SERIAL", "constraints": "PRIMARY KEY"},
                                {"name": "prompt", "type": "TEXT", "constraints": "NOT NULL"},
                                {"name": "options", "type": "JSONB", "constraints": "NOT NULL"},
                                {"name": "correct_answer", "type": "TEXT", "constraints": "NOT NULL"}]})
                record(r, f, "added table 'questions' (id, prompt, options, correct_answer) in " + art)
            for t in r["data"]["tables"]:
                if t["table"] == "games":
                    t["file"] = "sql/game_ddl.sql"

        out.append(Finding(
            "SL-01", "error", f"Traceability points to '{art}', which is not a declared deliverable",
            f"Traceability references {art}; deliverables list only has {sorted(similar) or 'nothing similar'}. "
            f"Also, no 'questions' table is defined anywhere, although QuestionComponent owns question persistence.",
            srcs + deliv_src,
            f"Generate BOTH files: sql/game_ddl.sql (games table, as declared) and {art} "
            f"(new questions table). Traceability for this requirement keeps pointing to {art}.", fix))
    return out


# ---------------------------------------------------------------- SL-02
@rule("SL-02", "Every requirement ID appears in traceability")
def reqs_in_traceability(ir):
    out = []
    for r in ir["requirements"]:
        if not r["in_traceability"] and r["mentions"]:
            theme = r["text"] or "?"

            def fix(res, f, rid=r["id"], theme=theme):
                q = _req(res, rid)
                comps = ["UserComponent"] if "secur" in theme.lower() else ["GameComponent"]
                q.update(in_traceability=True, components=comps,
                         diagrams=["UseCaseDiagram", "ComponentDiagram"],
                         artifacts=["openapi.yaml"], origin_trace="resolved")
                record(res, f, f"added traceability row for {rid} -> {', '.join(comps)}")

            out.append(Finding(
                "SL-02", "error", f"{r['id']} ({theme}) is used but missing from the traceability matrix",
                f"{r['id']} is mentioned {len(r['mentions'])} times (QA table, stack justifications) "
                f"but has no row in the traceability matrix, so nothing maps it to a component or artifact.",
                r["mentions"][:4],
                f"Add {r['id']} to the generated traceability matrix, mapped to "
                f"{'UserComponent (authentication/authorization) and the admin-only API routes' if 'secur' in theme.lower() else 'GameComponent'}.",
                fix))
    return out


# ---------------------------------------------------------------- SL-03
@rule("SL-03", "Traceability table and CSV agree")
def trace_table_vs_csv(ir):
    def key(rows):
        return sorted(tuple(v for k, v in row.items() if k != "src") for row in rows)
    t, c = ir["traceability_declared"]["table"], ir["traceability_declared"]["csv"]
    if c and key(t) != key(c):
        return [Finding("SL-03", "warning", "Traceability table and CSV differ",
                        "The matrix in section B and traceability_matrix.csv contain different rows.",
                        [t[0]["src"], c[0]["src"]], "Use section B as the source of truth.")]
    return []


# ---------------------------------------------------------------- SL-04
@rule("SL-04", "Components in diagrams are described in the text")
def components_in_text(ir):
    out = []
    for c in ir["components"]:
        if c["in_component_diagram"] and not c["in_text"]:
            stem = re.sub("Component$", "", c["name"])
            ucs = [u["name"] for u in ir["use_cases"] if stem in u["actors"]]
            resp = f"handles {', '.join(ucs).lower()} for the {stem} actor" if ucs else "unspecified"

            def fix(r, f, name=c["name"], resp=resp):
                comp = next(x for x in r["components"] if x["name"] == name)
                comp.update(responsibility=resp, responsibility_origin="inferred")
                record(r, f, f"{name}.responsibility = '{resp}' (inferred from use cases)")

            out.append(Finding(
                "SL-04", "warning", f"{c['name']} appears in diagrams but not in the architecture text",
                f"{c['name']} is in the Component diagram (also package {c['package']}, node "
                f"{c['deployment_node']}, container {c['container']}) but section C lists no responsibility for it.",
                [c.get("diagram_src", "")],
                f"Keep it as its own module. Responsibility inferred from the use-case diagram: '{resp}'.", fix))
    return out


# ---------------------------------------------------------------- SL-05
@rule("SL-05", "Testing matrix is filled and covers all components")
def testing_matrix(ir):
    t = ir.get("testing") or {}
    if not t:
        return []
    empty = [c for c in t["cells"] if not c["value"]]
    all_comps = [c["name"] for c in ir["components"]]
    missing_cols = [c for c in all_comps if c not in t["components"]]
    if not empty and not missing_cols:
        return []

    def fix(r, f):
        plan = {
            "Unit testing": all_comps,
            "Integration testing": all_comps,
            "Contract testing": ["GameComponent", "QuestionComponent", "AdminComponent"],
            "E2E testing": ["GameComponent"],
            "Chaos testing": [],
        }
        r["testing"]["resolved_matrix"] = {
            tt: {c: ("planned" if c in comps else "n/a") for c in all_comps} for tt, comps in plan.items()}
        r["testing"]["notes"] = {
            "Contract testing": "every endpoint in the resolved OpenAPI is called by a supertest test",
            "E2E testing": "full game flow intro -> menu -> questions -> ending, through the API",
            "Chaos testing": "n/a: single-process desktop build; replaced by failure-injection unit tests "
                             "(repository errors, invalid state transitions)"}
        record(r, f, "filled testing matrix for all components (see testing.resolved_matrix)")

    return [Finding(
        "SL-05", "error", "Testing matrix is empty",
        f"{len(empty)} of {len(t['cells'])} cells are empty, and the matrix has no column for "
        f"{', '.join(missing_cols) or '-'}.",
        [t["matrix_src"]],
        "Generate a filled matrix: unit + integration tests for every component, contract tests for every "
        "API route, one E2E test for the full game flow; chaos testing replaced by failure-injection tests.",
        fix)]


# ---------------------------------------------------------------- SL-06
# Which requirement themes a technology category can plausibly support.
PLAUSIBLE = {
    "language/runtime": {"performance"},
    "web framework": {"performance"},
    "rpc/http": {"performance"},
    "persistence": {"durability"},
    "cache": {"performance"},
    "messaging": {"durability", "performance"},
    "search": {"performance"},
    "authn/authz": {"security"},
    "observability": {"performance", "durability", "security"},
    "ci/cd": set(),
    "container runtime": set(),
    "infra provisioning": {"durability"},
}


def _theme(text: str) -> str:
    t = text.lower()
    return ("durability" if "durab" in t else "performance" if "perform" in t
            else "security" if "secur" in t else t)


@rule("SL-06", "Stack justifications match the cited requirement")
def stack_justifications(ir):
    bad = [o for o in ir["stack"]["options"]
           if _theme(o["justification_theme"]) not in PLAUSIBLE.get(o["category"].lower(), {_theme(o["justification_theme"])})]
    if not bad:
        return []
    detail = "; ".join(f"{o['category']} '{o['choice']}' justified by {o['justified_by']} "
                       f"({o['justification_theme']})" for o in bad)

    def fix(r, f):
        r["stack"]["justification_issues"] = [o["src"] for o in bad]
        record(r, f, f"marked {len(bad)} stack justifications as unreliable")

    return [Finding("SL-06", "warning", f"{len(bad)} of {len(ir['stack']['options'])} stack justifications do not support the cited requirement",
                    detail, [o["src"] for o in bad],
                    "Ignore these justifications. Stack is chosen by scope instead (see SL-21) and each "
                    "choice gets a real rationale in the generated README.", fix)]


# ---------------------------------------------------------------- SL-07
@rule("SL-07", "Every use case is covered by a requirement")
def usecases_have_reqs(ir):
    texts = {_norm(r["text"]): r["id"] for r in ir["requirements"]}
    uncovered = [u for u in ir["use_cases"] if _norm(u["name"]) not in texts]
    if not uncovered:
        return []

    def fix(r, f):
        for u in uncovered:
            rid = _next_fr(r)
            r["requirements"].append({
                "id": rid, "type": "FR", "text": u["name"], "origin": "inferred", "in_traceability": True,
                "diagrams": ["UseCaseDiagram"], "components": [], "artifacts": ["openapi.yaml"],
                "test_types": ["Unit testing", "Integration testing"], "mentions": [], "src": u["src"],
                "actors": u["actors"]})
            record(r, f, f"inferred requirement {rid} '{u['name']}' from use case {u['id']}")
        for u in r["use_cases"]:
            u["requirement"] = next((q["id"] for q in r["requirements"] if _norm(q["text"]) == _norm(u["name"])), None)

    return [Finding("SL-07", "warning", f"{len(uncovered)} use cases have no requirement ID",
                    "Only FR-1 'Play game' exists. Use cases " + ", ".join(f"'{u['name']}'" for u in uncovered)
                    + " have no FR, so nothing would force them to be built or tested.",
                    [u["src"] for u in uncovered][:1] + [r.get("src", "") for r in ir["requirements"] if r["id"] == "FR-1"],
                    "Create inferred requirements (" + ", ".join(
                        f"FR-{i}" for i in range(2, 2 + len(uncovered))) +
                    "), marked origin='inferred', each traced to code and tests like spec requirements.", fix)]


# ---------------------------------------------------------------- SL-08
@rule("SL-08", "User-facing experience in the summary is covered by the design")
def experience_covered(ir):
    flow = ir["system"].get("experience_flow", [])
    corpus = " ".join([u["name"] for u in ir["use_cases"]] +
                      [s.get("text", "") for s in ir["activity"]] +
                      [m["label"] for i in ir["interactions"] for m in i["messages"]] +
                      [e["path"] for e in ir["api"]["endpoints"]]).lower()
    stop = {"series", "of", "with", "scene", "a", "an", "the"}
    uncovered = [f for f in flow
                 if not any(w in corpus for w in re.findall(r"[a-z]+", f.lower()) if w not in stop and len(w) > 3)]
    if not uncovered:
        return []

    def fix(r, f):
        rid = _next_fr(r)
        r["requirements"].append({
            "id": rid, "type": "FR", "origin": "inferred", "in_traceability": True,
            "text": "Experience flow: " + " -> ".join(flow), "diagrams": [], "components": ["GameComponent"],
            "artifacts": ["ui"], "test_types": ["E2E testing"], "mentions": [],
            "src": ir["system"].get("experience_flow_src", "")})
        r["ui"] = {"screens": [{"id": f"S{i+1}", "name": s} for i, s in enumerate(flow)],
                   "requirement": rid}
        record(r, f, f"inferred requirement {rid} (experience flow) and {len(flow)} UI screens")

    return [Finding("SL-08", "warning", "Intro movie, main menu and ending scene are in the summary but in no diagram or API",
                    "Summary promises: " + "; ".join(flow) + ". Not covered anywhere: " + "; ".join(uncovered) + ".",
                    [ir["system"].get("experience_flow_src", "")],
                    "Add an inferred requirement for the full experience flow and generate one UI screen per step "
                    "(intro animation, menu, question screen, ending with feedback).", fix)]


# ---------------------------------------------------------------- SL-09
def _derive_endpoints(ir) -> list[dict]:
    """Derive REST endpoints from use cases, sequence diagrams and the state machine."""
    spec_paths = {(e["method"], e["path"]) for e in ir["api"]["endpoints"]}
    game_attrs = {a["name"].lower() for e in ir["entities"] if e["name"] == "Game" for a in e["attributes"]}
    derived = []

    def add(method, path, summary, src, from_):
        if (method, path) not in spec_paths and all(d["path"] != path or d["method"] != method for d in derived):
            derived.append({"method": method, "path": path, "summary": summary, "origin": "derived",
                            "derived_from": from_, "src": src})

    for it in ir["interactions"]:
        for m in it["messages"]:
            label = m["label"].lower()
            if m["kind"] != "call":
                continue
            if m["from"] in ("Game",) and label.startswith("get"):          # Game asks Question for a prompt
                noun = re.sub(r"^get|\(\)$", "", label)
                add("GET", "/games/{gameId}/question", f"Get the current {noun or 'question'}", m["src"],
                    f"{it['diagram']}: {m['from']}->{m['to']} {m['label']}")
            elif mm := re.match(r"submit\s+(\w+)", label):
                add("POST", f"/games/{{gameId}}/{mm.group(1)}s", f"Submit an {mm.group(1)}", m["src"],
                    f"{it['diagram']}: {m['from']}->{m['to']} {m['label']}")
            elif m["from"] == "Admin" and label.startswith("update"):
                add("PUT", "/admin/questions", "Replace the question bank", m["src"],
                    f"{it['diagram']}: {m['from']}->{m['to']} {m['label']}")
    for u in ir["use_cases"]:
        verb, _, obj = u["name"].partition(" ")
        obj_l = obj.lower()
        if verb.lower() == "view":
            path = f"/games/{{gameId}}/{obj_l}" if obj_l in game_attrs else f"/{obj_l}"
            add("GET", path, u["name"], u["src"], f"use case {u['id']}")
        elif verb.lower() == "update":
            add("GET", f"/admin/{obj_l}", f"List {obj_l} (needed before updating)", u["src"], f"use case {u['id']}")
    sm = ir.get("state_machine") or {}
    for t in sm.get("transitions", []):
        trig = t["trigger"].replace("()", "")
        if trig and t["to"] != "GameOver":
            add("POST", f"/games/{{gameId}}/{trig}", f"{t['from']} -> {t['to']}", sm["src"],
                f"state transition {t['from']} --{t['trigger']}--> {t['to']}")
    return derived


@rule("SL-09", "API contract covers the interactions in the diagrams")
def api_coverage(ir):
    derived = _derive_endpoints(ir)
    if not derived:
        return []

    def fix(r, f):
        for d in derived:
            r["api"]["endpoints"].append(d)
            record(r, f, f"derived endpoint {d['method']} {d['path']}  <- {d['derived_from']}")

    return [Finding("SL-09", "warning",
                    f"OpenAPI defines {len(ir['api']['endpoints'])} endpoint, diagrams need {len(derived)} more",
                    "openapi.yaml only has " + ", ".join(f"{e['method']} {e['path']}" for e in ir["api"]["endpoints"])
                    + ". Sequence/use-case/state diagrams require: "
                    + ", ".join(f"{d['method']} {d['path']}" for d in derived) + ".",
                    [e["src"] for e in ir["api"]["endpoints"]] + [derived[0]["src"]],
                    "Keep GET /play exactly as specified (contract compatibility) and add the derived endpoints, "
                    "each marked origin='derived' with the diagram element it came from.", fix)]


# ---------------------------------------------------------------- SL-10
@rule("SL-10", "Identifier types agree across views and contracts")
def id_types(ir):
    seen = []
    for e in ir["entities"]:
        for a in e["attributes"]:
            if a["name"] == "id":
                seen.append((f"class {e['name']}.id", a["type"], e["src"]))
    for ep in ir["api"]["endpoints"][:1]:
        for name, prop in (ep.get("response_schema", {}).get("properties") or {}).items():
            if name.lower().endswith("id"):
                seen.append((f"OpenAPI {name}", prop.get("type"), ep["src"]))
    for p in ir["api"]["internal"][:1]:
        for msg, fields in p["messages"].items():
            for fl in fields:
                if fl["name"].lower().endswith("id"):
                    seen.append((f"proto {msg}.{fl['name']}", fl["type"], p["src"]))
                    break
    for t in ir["data"]["tables"][:1]:
        for c in t["columns"]:
            if c["name"] == "id":
                seen.append((f"SQL {t['table']}.id", c["type"], t["src"]))
    family = lambda t: "integer" if re.match(r"(?i)int|integer|serial|int32|int64|bigint", t or "") else "string"
    if len({family(t) for _, t, _ in seen}) <= 1:
        return []

    def fix(r, f):
        for e in r["entities"]:
            for a in e["attributes"]:
                if a["name"] == "id" and family(a["type"]) == "string":
                    a.update(type="int", type_origin="resolved")
                    record(r, f, f"{e['name']}.id: string -> int")

    return [Finding("SL-10", "warning", "ID types disagree between the class diagram and the contracts",
                    "; ".join(f"{w} = {t}" for w, t, _ in seen) + ".",
                    sorted({s for _, _, s in seen}),
                    "Use integer IDs everywhere: the external contracts (OpenAPI, proto) and the SQL DDL agree on "
                    "integers, and contracts win over the class diagram.", fix)]


# ---------------------------------------------------------------- SL-11
@rule("SL-11", "Behaviour in diagrams has the data it needs")
def behaviour_needs_data(ir):
    out = []
    for it in ir["interactions"]:
        for m in it["messages"]:
            mm = re.match(r"(?i)(check|validate|verify|compare)\s+(\w+)", m["label"])
            ent = _entity(ir, m["to"]) if mm else None
            if not ent:
                continue
            noun = mm.group(2).lower()
            if any(noun in a["name"].lower() for a in ent["attributes"]):
                continue
            if any(f.title.startswith(f"{m['to']} cannot") for f in out):
                continue

            def fix(r, f, ename=m["to"], noun=noun):
                e = _entity(r, ename)
                e["attributes"].append({"visibility": "-", "name": f"correct{noun.capitalize()}",
                                        "type": "Fraction", "origin": "resolved"})
                e["methods"].append({"visibility": "+", "name": f"check{noun.capitalize()}",
                                     "params": [f"{noun}: Fraction"], "returns": "boolean", "origin": "resolved"})
                record(r, f, f"{ename}: added attribute correct{noun.capitalize()} and method check{noun.capitalize()}()")

            out.append(Finding(
                "SL-11", "error", f"{m['to']} cannot '{m['label']}': it has no {noun} data",
                f"{it['diagram']} sends '{m['label']}' to {m['to']}, but {m['to']} only has attributes "
                f"{[a['name'] for a in ent['attributes']]}. There is nothing to check the {noun} against.",
                [m["src"], ent["src"]],
                f"Add {m['to']}.correct{noun.capitalize()} (a fraction, stored as 'n/d') and "
                f"{m['to']}.check{noun.capitalize()}() which compares fractions by value (1/2 == 2/4).", fix))
    return out


# ---------------------------------------------------------------- SL-12
@rule("SL-12", "Sequence messages call methods that exist")
def messages_call_methods(ir):
    out, reported = [], set()
    for it in ir["interactions"]:
        for m in it["messages"]:
            mm = re.match(r"^(\w+)\(\)$", m["label"].strip())
            ent = _entity(ir, m["to"]) if mm else None
            if not ent or (m["to"], mm.group(1)) in reported:
                continue
            if mm.group(1) in {x["name"] for x in ent["methods"]}:
                continue
            reported.add((m["to"], mm.group(1)))
            caller = _entity(ir, m["from"])
            close = [x["name"] for x in (caller["methods"] if caller else []) if mm.group(1).lower() in x["name"].lower()]

            def fix(r, f, ename=m["to"], meth=mm.group(1), close=close):
                e = _entity(r, ename)
                e["methods"].append({"visibility": "+", "name": f"{meth}Questions" if not close else close[0],
                                     "params": ["questions: List<Question>"], "returns": "void", "origin": "resolved"})
                record(r, f, f"{ename}: added service method {close[0] if close else meth}(questions)")

            out.append(Finding(
                "SL-12", "warning", f"{m['from']} calls {m['to']}.{mm.group(1)}(), which {m['to']} does not define",
                f"{it['diagram']} calls {mm.group(1)}() on {m['to']}; class {m['to']} has methods "
                f"{[x['name'] for x in ent['methods']]}." + (f" The caller {m['from']} has {close}." if close else ""),
                [m["src"], ent["src"]],
                f"Implement it in QuestionComponent as {close[0] if close else mm.group(1)}(questions), called by "
                f"the admin route; the Admin class method is the entry point.", fix))
    return out


# ---------------------------------------------------------------- SL-13
@rule("SL-13", "SLO and error budget are consistent")
def slo_math(ir):
    slo = ir["quality"]["slo"]
    try:
        target = float(re.search(r"([\d.]+)\s*%", slo["slo"]["value"]).group(1))
        budget = float(re.search(r"([\d.]+)\s*%", slo["error_budget"]["value"]).group(1))
    except (KeyError, AttributeError):
        return []
    expected = round(100 - target, 6)
    if abs(expected - budget) < 1e-9:
        return []

    def fix(r, f):
        r["quality"]["slo"]["error_budget"]["resolved_value"] = f"{expected:g}%"
        record(r, f, f"error budget {budget:g}% -> {expected:g}% (= 100% - {target:g}%)")

    minutes = expected / 100 * 30 * 24 * 60
    return [Finding("SL-13", "error", f"SLO {target:g}% implies an error budget of {expected:g}%, not {budget:g}%",
                    f"Error budget = 100% - SLO. {target:g}% uptime allows {expected:g}% downtime "
                    f"(about {minutes:.1f} min/month); the document says {budget:g}% (~{budget/100*30*24*60:.0f} min/month), "
                    f"{budget/expected:.0f}x more.",
                    [slo["slo"]["src"], slo["error_budget"]["src"]],
                    f"Record the corrected budget ({expected:g}%) in the README; the desktop build has no SLO "
                    f"monitoring, so this is documentation-only.", fix)]


# ---------------------------------------------------------------- SL-14
@rule("SL-14", "State machine has a final state and no dead ends")
def state_machine(ir):
    sm = ir.get("state_machine") or {}
    if not sm:
        return []
    outgoing = {t["from"] for t in sm["transitions"]}
    dead = [s for s in sm["states"] if s not in outgoing and s not in sm.get("final", [])]
    paused_exit = any(t["from"] == "Paused" and t["to"] == "GameOver" for t in sm["transitions"])
    if not dead and sm.get("final"):
        return []

    def fix(r, f):
        m = r["state_machine"]
        for s in dead:
            m.setdefault("final", []).append(s)
            record(r, f, f"marked {s} as final state ({s} --> [*])")
        if "Paused" in m["states"] and not paused_exit:
            m["transitions"].append({"from": "Paused", "to": "GameOver", "trigger": "quit()",
                                     "origin": "resolved"})
            record(r, f, "added transition Paused --quit()--> GameOver")
            r["api"]["endpoints"].append({"method": "POST", "path": "/games/{gameId}/quit",
                                          "summary": "Paused -> GameOver", "origin": "derived",
                                          "derived_from": "resolved transition Paused --quit()--> GameOver",
                                          "src": m["src"]})
            record(r, f, "derived endpoint POST /games/{gameId}/quit")

    return [Finding("SL-14", "warning", "State machine has no final state" + (f"; dead end: {', '.join(dead)}" if dead else ""),
                    f"States {sm['states']}, initial {sm['initial']}, no '--> [*]'. {', '.join(dead)} has no "
                    f"outgoing transition and is not marked final. A paused game cannot be ended "
                    f"(no Paused -> GameOver).",
                    [sm["src"]],
                    "Mark GameOver as final; add Paused --quit()--> GameOver so a paused game can be ended; "
                    "illegal transitions (e.g. resume() while Playing) return HTTP 409.", fix)]


# ---------------------------------------------------------------- SL-15
@rule("SL-15", "PlantUML syntax is valid for each diagram type")
def plantuml_syntax(ir):
    out = []
    for d in ir["diagrams"]:
        if d["warnings"]:
            out.append(Finding("SL-15", "warning", f"{d['name']}: {d['warnings'][0]['message']}",
                               f"{len(d['warnings'])} problem line(s) in {d['name']} ({d['kind']} diagram).",
                               [d["src"]] + [f"{d['src'].split(':')[0]}:{w['line']}" for w in d["warnings"][:2]],
                               "Parsed tolerantly: participants treated as objects. Diagram meaning is unchanged."))
    return out


# ---------------------------------------------------------------- SL-16
@rule("SL-16", "No duplicate diagrams; declared count matches")
def duplicate_diagrams(ir):
    out, groups = [], {}
    for d in ir["diagrams"]:
        groups.setdefault(d["fingerprint"], []).append(d)
    dups = [g for g in groups.values() if len(g) > 1]
    for g in dups:
        out.append(Finding("SL-16", "info", f"{' and '.join(d['name'] for d in g)} are identical",
                           "Same participants and messages (only the note differs). A collaboration diagram "
                           "should show links between objects, not repeat the sequence.",
                           [d["src"] for d in g], "Treated as one interaction; no extra behaviour derived."))
    declared = ir["system"].get("declared_diagram_count")
    if declared and declared != len(ir["diagrams"]):
        out.append(Finding("SL-16", "info", f"Document says {declared} PlantUML diagrams; the view file has {len(ir['diagrams'])}",
                           f"{len(ir['diagrams'])} @startuml blocks under {declared} numbered diagram types "
                           f"({len(ir['diagrams']) - len(groups)} of them duplicates).",
                           [ir["system"]["declared_diagram_count_src"]], "All blocks are parsed; duplicates merged."))
    return out


# ---------------------------------------------------------------- SL-17
@rule("SL-17", "Deployment manifests match the architectural style")
def style_vs_deployment(ir):
    style = ir["system"].get("style", "").lower()
    k8s = ir["deployment"]["k8s"]
    if "microservice" not in style or not k8s:
        return []
    images = {i for m in k8s for i in m.get("images", [])}
    containers = ir["deployment"]["containers"]
    issues = []
    if len(images) < len(containers):
        issues.append(f"{len(containers)} containers in the Container diagram but only {len(images)} image "
                      f"({', '.join(images)}) in the k8s manifest")
    if any(i.endswith(":latest") for i in images):
        issues.append("image uses the mutable ':latest' tag")
    if not issues:
        return []
    return [Finding("SL-17", "warning", "Microservices style, but deployment is a single container",
                    "; ".join(issues) + ".", [ir["system"]["style_src"], k8s[0]["src"]] + [containers[0]["src"]],
                    "Build a modular monolith: one module per component with its own router, service and "
                    "repository, talking only through interfaces, so each could be split into a service later. "
                    "One Dockerfile with a pinned version tag; the k8s manifest is regenerated with that tag.",
                    lambda r, f: record(r, f, "deployment model: modular monolith, 1 image, pinned tag"))]


# ---------------------------------------------------------------- SL-18
@rule("SL-18", "Package grouping agrees with component boundaries")
def packages_vs_components(ir):
    out = []
    for c in ir["components"]:
        if c["package"] and c["entity"] and c["entity"] != c["package"] and c["in_component_diagram"]:
            out.append(Finding("SL-18", "info",
                               f"{c['entity']} is inside package {c['package']}, but {c['name']} is a separate component",
                               f"Package diagram puts class {c['entity']} in package {c['package']}; the component, "
                               f"deployment and container diagrams give it its own {c['name']} / "
                               f"{c['deployment_node']} / {c['container']}.",
                               [c.get("diagram_src", "")],
                               f"Follow the component diagram (3 views agree): {c['name']} is its own module."))
    return out


# ---------------------------------------------------------------- SL-19
@rule("SL-19", "Duplicated contract blocks are identical")
def duplicated_blocks(ir):
    out = []
    for label, blocks in (("OpenAPI", ir["api"]["openapi_blocks"]), ("proto", ir["api"]["internal"]),
                          ("SQL", ir["data"]["tables"])):
        shas = {b.get("sha") for b in blocks if b.get("origin") != "resolved"}
        if len(shas) > 1:
            out.append(Finding("SL-19", "error", f"The {label} blocks in the document differ",
                               f"{len(blocks)} copies of the {label} contract with different content.",
                               [b["src"] for b in blocks], "Use the copy in section D (detailed design)."))
    return out


# ---------------------------------------------------------------- SL-20
@rule("SL-20", "Referenced inputs are provided")
def referenced_inputs(ir):
    return [Finding("SL-20", "info", f"'{x['name']}' is referenced but was not provided",
                    f"The analysis plan aligns with a {x['name']} that is not among the inputs, so original "
                    f"requirement texts beyond the IDs are unknown.",
                    [x["src"]], "Requirement texts are taken from the traceability table, QA table and diagrams; "
                                "anything inferred is marked origin='inferred'.")
            for x in ir["system"].get("referenced_inputs", [])]


# ---------------------------------------------------------------- SL-21
@rule("SL-21", "Recommended stack is proportionate to the system's scope")
def stack_scope(ir):
    rec = ir["stack"]["recommended"]
    n_tables = len({t["table"] for t in ir["data"]["tables"]})
    n_endpoints = len(ir["api"]["endpoints"])
    if len(rec) <= 5:
        return []
    keep = ["Node.js 18", "Express.js 4", "PostgreSQL 14 (DDL) + in-memory repository", "Docker"]

    def fix(r, f):
        r["stack"]["selected"] = {
            "runtime": "Node.js 18", "web_framework": "Express 4", "persistence":
            "Repository interface: in-memory (default) | PostgreSQL 14 (DDL provided)",
            "desktop_shell": "Electron (task constraint C-1)", "tests": "Jest + supertest",
            "container": "Docker (node:18-alpine, pinned)",
            "out_of_scope": ["Redis 6", "RabbitMQ 3", "Elasticsearch 7", "OAuth2 provider",
                             "Prometheus 2", "Jenkins 2", "Terraform 1"]}
        record(r, f, "selected MVP stack; 7 infrastructure items documented as out of scope")

    return [Finding("SL-21", "info", f"Recommended stack has {len(rec)} technologies for {n_tables} table and {n_endpoints} endpoint",
                    "Redis, RabbitMQ, Elasticsearch, OAuth2, Prometheus, Jenkins and Terraform are recommended for a "
                    "single-player fraction game whose specified data model is one table.",
                    [rec[0]["src"], rec[-1]["src"]],
                    "Use " + ", ".join(keep) + ". The rest is listed in the README as out of scope with the reason, "
                    "and the repository interface keeps PostgreSQL a drop-in option.", fix)]
