"""Planning: deterministic skeleton + Architect sub-agent + validator.

1. SKELETON (code)   fixed project layout derived from the IR components:
                     core (domain + app wiring), one work package per component, desktop UI.
2. ARCHITECT (LLM)   one call, thinking mode, JSON output: module interfaces
                     (exports with signatures), data shapes, per-endpoint contracts
                     (request/response/errors) and which requirement each piece implements.
3. VALIDATOR (code)  rejects plans that miss an endpoint or a requirement or put files
                     outside the layout; one retry with the errors; then a deterministic
                     fallback fills any remaining gap. A bad LLM answer can therefore
                     never produce an incomplete plan.
"""

from __future__ import annotations

import fnmatch
import json
import re

from .digest import component_slug, endpoint_reqs

CONVENTIONS = [
    "CommonJS modules (require/module.exports), Node.js 18+, Express 4. No dependencies beyond package.json.",
    "src/app.js exports createApp(options) -> Express app (does NOT listen). options.store lets tests inject "
    "an in-memory store; default store is createFileStore(process.env.DATA_FILE || 'data/store.json'). "
    "createApp also serves the public/ folder as static files at '/' (express.static) and parses JSON bodies.",
    "src/server.js exports start(port) -> Promise<{server, port}>: it passes port straight to listen() "
    "(port 0 = the OS picks a free port; use `port ?? process.env.PORT ?? 3000`, never `||`) and resolves with the "
    "ACTUAL port from server.address().port. Run directly, it listens on process.env.PORT or 3000.",
    "Persistence: a store with the same interface in two implementations: createMemoryStore() and "
    "createFileStore(filePath) (JSON file, atomic write: write temp file then rename) -> ASR-1 durability.",
    "Out-of-the-box playable: src/domain/seedQuestions.js exports the plan's seed questions; a NEW store "
    "(memory store, or file store whose file does not exist yet) starts with them, so a fresh install can play "
    "immediately. createMemoryStore({ empty: true }) gives an empty store.",
    "Errors are JSON: {\"error\": {\"code\": \"SNAKE_CASE\", \"message\": \"...\"}} with status 400 (invalid input), "
    "401 (missing admin token), 403 (wrong admin token), 404 (unknown id), 409 (illegal state transition). "
    "Use a specific code per situation (e.g. GAME_NOT_FOUND vs NO_QUESTIONS).",
    "Never leave scratch, debug or temporary files in the project; check code with node --check and npx jest.",
    "Admin routes require header 'x-admin-token' equal to options.adminToken (default process.env.ADMIN_TOKEN "
    "or 'dev-admin-token') -> ASR-2.",
    "Fractions are strings 'n/d' (or integers); answers are compared by value (1/2 == 2/4).",
    "State rules apply to EVERY game endpoint, not only to transitions: while a game is Paused or GameOver, "
    "GET /games/:id/question and POST /games/:id/answers return 409 NOT_PLAYING; only resume/quit/score work.",
    "Fair play: when a game starts, the server shuffles the ORDER OF THE OPTIONS of every question for that game "
    "(not only the order of questions), so the correct answer is not always in the same position; the API never "
    "reveals which option is correct before the answer is submitted.",
    "Every exported function and route handler has a comment '// @req <ID>' naming the requirement(s) it implements.",
]


def skeleton(ir: dict) -> list[dict]:
    """Work packages with their write scopes. Order = build order."""
    wps = [{"id": "core", "title": "Domain logic, store and app wiring",
            "scope": ["src/app.js", "src/server.js", "src/domain/*", "src/store/*"]}]
    comps = [c["name"] for c in ir["components"]]
    # build order: data owners first (question), then the component that uses them (game), then the rest
    order = sorted(comps, key=lambda n: {"question": 0, "game": 1}.get(component_slug(n), 2))
    for c in order:
        slug = component_slug(c)
        wps.append({"id": slug, "title": c, "scope": [f"src/components/{slug}/*"]})
    wps.append({"id": "ui", "title": "Desktop UI (Electron shell + screens)",
                "scope": ["electron/*", "public/*"]})
    return wps


ARCHITECT_TASK = """You are the ARCHITECT. Design the implementation contract for the project described in the
project context. Do not write code. Answer with ONE JSON object only, with exactly these keys:

{
  "summary": "3-5 sentences: the architecture and how components interact",
  "data_shapes": {"Game": {"field": "type and meaning"}, "Question": {...}},
  "modules": [
    {"path": "src/...", "work_package": "<one of: WORK_PACKAGES>", "purpose": "one line",
     "exports": ["name(params) -> return: one-line behaviour"], "reqs": ["FR-1"]}
  ],
  "api": [
    {"method": "GET", "path": "/play", "module": "src/components/.../x.js",
     "request": "body/params or none", "response": "status + JSON shape", "errors": ["409 NOT_PLAYING when ..."],
     "reqs": ["FR-1"]}
  ],
  "ui_screens": [{"id": "intro", "behaviour": "what the user sees/does, which endpoints it calls"}],
  "seed_questions": ["prompt | correct answer as n/d | 3 wrong options"]  (8 grade-6 fraction questions)
}

Rules:
- Every file path must match one of these work-package scopes: SCOPES
- "api" must contain EVERY endpoint listed in the project context, with the exact method and path.
- Every requirement ID (FR/NFR/ASR) must appear in at least one module or api entry.
- Follow these conventions: CONVENTIONS
- Keep it small: about 14-20 modules in total. The game must be playable end to end."""


def architect_prompt(wps: list[dict]) -> str:
    return (ARCHITECT_TASK.replace("WORK_PACKAGES", ", ".join(w["id"] for w in wps))
            .replace("SCOPES", "; ".join(f"{w['id']}: {', '.join(w['scope'])}" for w in wps))
            .replace("CONVENTIONS", " | ".join(CONVENTIONS)))


def parse_json(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)          # tolerate prose or ``` fences around the JSON
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def validate_plan(plan: dict, ir: dict, wps: list[dict]) -> list[str]:
    errs = []
    if not isinstance(plan, dict):
        return ["plan is not a JSON object"]
    for key in ("summary", "modules", "api"):
        if key not in plan:
            errs.append(f"missing key '{key}'")
    scopes = {w["id"]: w["scope"] for w in wps}
    for m in plan.get("modules", []):
        wp, path = m.get("work_package"), m.get("path", "")
        if wp not in scopes:
            errs.append(f"module {path}: unknown work_package '{wp}'")
        elif not any(fnmatch.fnmatch(path, p) for p in scopes[wp]):
            errs.append(f"module {path}: outside scope of work package '{wp}' {scopes[wp]}")
    have = {f"{a.get('method', '').upper()} {a.get('path', '')}" for a in plan.get("api", [])}
    for k in endpoint_reqs(ir):
        if k not in have:
            errs.append(f"api is missing endpoint {k}")
    covered = {r for m in plan.get("modules", []) for r in m.get("reqs", [])} | \
              {r for a in plan.get("api", []) for r in a.get("reqs", [])}
    for r in ir["requirements"]:
        if r["id"] not in covered:
            errs.append(f"requirement {r['id']} ({r['text'][:40]}) is not covered by any module or api entry")
    for w in wps:
        if not any(m.get("work_package") == w["id"] for m in plan.get("modules", [])):
            errs.append(f"work package '{w['id']}' has no modules")
    return errs


def repair_plan(plan: dict, ir: dict, wps: list[dict]) -> tuple[dict, list[str]]:
    """Deterministic fallback: fill whatever the validator still complains about."""
    plan = dict(plan or {})
    plan.setdefault("summary", "Modular monolith: one module per component behind an Express app, "
                               "wrapped in an Electron desktop shell.")
    plan.setdefault("modules", [])
    plan.setdefault("api", [])
    plan.setdefault("data_shapes", {})
    plan.setdefault("ui_screens", [])
    fixes = []
    scopes = {w["id"]: w["scope"] for w in wps}
    plan["modules"] = [m for m in plan["modules"] if m.get("work_package") in scopes and
                       any(fnmatch.fnmatch(m.get("path", ""), p) for p in scopes[m["work_package"]])]
    have = {f"{a.get('method', '').upper()} {a.get('path', '')}" for a in plan["api"]}
    for k, reqs in endpoint_reqs(ir).items():
        if k not in have:
            method, path = k.split(" ", 1)
            slug = "admin" if path.startswith("/admin") else "game"
            plan["api"].append({"method": method, "path": path, "module": f"src/components/{slug}/{slug}Router.js",
                                "request": "see project context", "response": "200 JSON", "errors": [],
                                "reqs": reqs})
            fixes.append(f"added missing endpoint {k}")
    for w in wps:
        if not any(m.get("work_package") == w["id"] for m in plan["modules"]):
            path = {"core": "src/app.js", "ui": "public/app.js"}.get(w["id"], f"{w['scope'][0][:-1]}index.js")
            plan["modules"].append({"path": path, "work_package": w["id"], "purpose": w["title"],
                                    "exports": [], "reqs": []})
            fixes.append(f"added placeholder module for work package {w['id']}")
    covered = {r for m in plan["modules"] for r in m.get("reqs", [])} | {r for a in plan["api"] for r in a.get("reqs", [])}
    for r in ir["requirements"]:
        if r["id"] not in covered:
            target = next((m for m in plan["modules"] if m["work_package"] == "core"), plan["modules"][0])
            target.setdefault("reqs", []).append(r["id"])
            fixes.append(f"assigned {r['id']} to {target['path']}")
    return plan, fixes


def plan_markdown(plan: dict) -> str:
    L = ["# Implementation plan (Architect)", "", plan.get("summary", ""), "", "## Modules", "",
         "| Path | Work package | Exports | Reqs |", "|---|---|---|---|"]
    for m in plan["modules"]:
        L.append(f"| `{m['path']}` | {m['work_package']} | {'<br>'.join(m.get('exports', []))[:300]} | "
                 f"{', '.join(m.get('reqs', []))} |")
    L += ["", "## API contract", "", "| Endpoint | Module | Response | Errors | Reqs |", "|---|---|---|---|---|"]
    for a in plan["api"]:
        L.append(f"| `{a['method']} {a['path']}` | `{a.get('module', '')}` | {a.get('response', '')} | "
                 f"{'; '.join(a.get('errors', []))} | {', '.join(a.get('reqs', []))} |")
    return "\n".join(L)
