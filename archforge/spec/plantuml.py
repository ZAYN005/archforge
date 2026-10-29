"""PlantUML parser for the 4+1 architectural views.

Finds every @startuml ... @enduml block, works out which kind of diagram it
is, and extracts its elements into plain dicts:

  usecase    actors, use cases, actor-usecase links
  class      classes (attributes with visibility/type, methods with params/return), relations
  object     objects and links
  state      states, initial/final markers, transitions with triggers
  activity   ordered steps and decisions
  sequence   participants, ordered messages (call/return), scenario notes
  package    packages and the classes inside them, links
  component / deployment / container   elements and links

It is deliberately tolerant: an unknown line becomes a warning instead of a
crash, because real specs are messy. Syntax problems (e.g. an object
diagram written with sequence-diagram keywords) are recorded as warnings
that the Spec Lint later reports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_START = re.compile(r"^\s*@startuml\s*(\S*)")
_END = re.compile(r"^\s*@enduml")
_VIEW_HEADING = re.compile(r"^##\s+(\w+View)\s*$")
_CAPTION = re.compile(r"^\s*\d+\.\s+(\w+)\s+[—\-]+\s+(.*)$")

# link between two names:  A -- B   A --> B   A --* B   A ..> B  (optional ": label")
_LINK = re.compile(r"^\s*(\(?[\w\[\]*]+\)?)\s+([-.*o<>|]+)\s+(\(?[\w\[\]*]+\)?)\s*(?::\s*(.*))?$")
# sequence message:  A->>B: text   A->B: text   A-->B: text
_MSG = re.compile(r"^\s*(\w+)\s*(-{1,2}>{1,2})\s*(\w+)\s*:\s*(.*\S)\s*$")


@dataclass
class Diagram:
    name: str
    kind: str
    view: str = ""
    caption: str = ""
    line: int = 0                      # line of @startuml in the source file
    source: str = ""                   # raw PlantUML body
    data: dict = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)

    def warn(self, line: int, msg: str) -> None:
        self.warnings.append({"line": line, "message": msg})

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "view": self.view, "caption": self.caption,
                "line": self.line, "data": self.data, "warnings": self.warnings}


def _strip(name: str) -> str:
    return name.strip().strip("()[]")


def _guess_kind(name: str, body: list[str]) -> str:
    n = name.lower()
    for k in ("usecase", "class", "object", "state", "activity", "sequence", "collaboration",
              "package", "component", "deployment", "container"):
        if k in n:
            return "sequence" if k == "collaboration" else k
    text = "\n".join(body)
    if re.search(r"^\s*actor\b", text, re.M):
        return "usecase"
    if re.search(r"^\s*class\s+\w+\s*\{", text, re.M):
        return "class"
    if "[*]" in text:
        return "state"
    if re.search(r"^\s*start\s*$", text, re.M):
        return "activity"
    if _MSG.search(text):
        return "sequence"
    return "unknown"


# ------------------------------------------------------------------ parsers
def _parse_usecase(d: Diagram, body):
    actors, usecases, links = {}, {}, []
    for ln, t in body:
        if m := re.match(r'^\s*actor\s+(\w+)(?:\s+as\s+"([^"]+)")?', t):
            actors[m.group(1)] = m.group(2) or m.group(1)
        elif m := re.match(r'^\s*usecase\s+"([^"]+)"\s+as\s+\(?(\w+)\)?', t):
            usecases[m.group(2)] = m.group(1)
        elif (m := _LINK.match(t)) and not t.strip().startswith(("left", "rectangle")):
            links.append({"actor": _strip(m.group(1)), "usecase": _strip(m.group(3)), "line": ln})
    d.data = {"actors": actors, "usecases": usecases, "links": links}


def _parse_class(d: Diagram, body):
    classes, relations, cur = {}, [], None
    for ln, t in body:
        s = t.strip()
        if m := re.match(r"^class\s+(\w+)\s*\{?", s):
            cur = m.group(1)
            classes[cur] = {"attributes": [], "methods": [], "line": ln}
            if not s.endswith("{"):
                cur = None
        elif s == "}":
            cur = None
        elif cur and (m := re.match(r"^([-+#~])\s*(\w+)\s*\(([^)]*)\)\s*(?::\s*(.+))?$", s)):
            params = [p.strip() for p in m.group(3).split(",") if p.strip()]
            classes[cur]["methods"].append({"visibility": m.group(1), "name": m.group(2),
                                            "params": params, "returns": (m.group(4) or "void").strip()})
        elif cur and (m := re.match(r"^([-+#~])\s*(\w+)\s*:\s*(.+)$", s)):
            classes[cur]["attributes"].append({"visibility": m.group(1), "name": m.group(2),
                                               "type": m.group(3).strip()})
        elif m := _LINK.match(s):
            relations.append({"from": m.group(1), "arrow": m.group(2), "to": m.group(3), "line": ln})
        elif s:
            d.warn(ln, f"unrecognised class-diagram line: {s}")
    d.data = {"classes": classes, "relations": relations}


def _parse_object(d: Diagram, body):
    objects, links = [], []
    for ln, t in body:
        s = t.strip()
        if m := re.match(r"^object\s+(\w+)", s):
            objects.append(m.group(1))
        elif m := re.match(r"^participant\s+(\w+)", s):
            objects.append(m.group(1))
            d.warn(ln, "object diagram uses 'participant' (sequence-diagram keyword); expected 'object'")
        elif m := _LINK.match(s):
            links.append({"from": m.group(1), "to": m.group(3), "line": ln})
    d.data = {"objects": objects, "links": links}


def _parse_state(d: Diagram, body):
    states, transitions, initial, final = [], [], None, []
    for ln, t in body:
        s = t.strip()
        if m := re.match(r"^state\s+(\w+)", s):
            states.append(m.group(1))
        elif m := re.match(r"^(\[\*\]|\w+)\s*-+>\s*(\[\*\]|\w+)\s*(?::\s*(.+))?$", s):
            a, b, trig = m.group(1), m.group(2), (m.group(3) or "").strip()
            if a == "[*]":
                initial = b
            elif b == "[*]":
                final.append(a)
            else:
                transitions.append({"from": a, "to": b, "trigger": trig, "line": ln})
            for x in (a, b):
                if x != "[*]" and x not in states:
                    states.append(x)
    d.data = {"states": states, "initial": initial, "final": final, "transitions": transitions}


def _parse_activity(d: Diagram, body):
    steps = []
    for ln, t in body:
        s = t.strip()
        if m := re.match(r"^:(.+);$", s):
            steps.append({"type": "action", "text": m.group(1), "line": ln})
        elif m := re.match(r"^if\s*\((.+?)\)\s*then\s*\((.+?)\)", s):
            steps.append({"type": "decision", "text": m.group(1), "branch": m.group(2), "line": ln})
        elif s in ("start", "stop", "endif") or s.startswith("else"):
            steps.append({"type": s.split()[0], "line": ln})
    d.data = {"steps": steps}


def _parse_sequence(d: Diagram, body):
    participants, messages, notes = [], [], []
    for ln, t in body:
        s = t.strip()
        if m := re.match(r"^(participant|actor)\s+(\w+)", s):
            participants.append(m.group(2))
        elif m := _MSG.match(s):
            label = m.group(4)
            kind = "return" if label.lower().startswith("return") else "call"
            messages.append({"from": m.group(1), "to": m.group(3), "label": label,
                             "kind": kind, "line": ln})
        elif m := re.match(r"^note\s+\w+\s+of\s+(\w+)\s*:\s*(.+)$", s):
            notes.append({"on": m.group(1), "text": m.group(2), "line": ln})
    scenario = next((re.sub(r"(?i)^scenario:\s*", "", n["text"]) for n in notes
                     if n["text"].lower().startswith("scenario")), "")
    d.data = {"participants": participants, "messages": messages, "notes": notes, "scenario": scenario}


def _parse_package(d: Diagram, body):
    packages, links, cur = {}, [], None
    for ln, t in body:
        s = t.strip()
        if m := re.match(r"^package\s+(\w+)\s*\{", s):
            cur = m.group(1)
            packages[cur] = []
        elif s == "}":
            cur = None
        elif cur and (m := re.match(r"^class\s+(\w+)", s)):
            packages[cur].append(m.group(1))
        elif m := _LINK.match(s):
            links.append({"from": m.group(1), "to": m.group(3), "line": ln})
    d.data = {"packages": packages, "links": links}


def _parse_boxes(d: Diagram, body):
    """component / deployment / container diagrams: named boxes + links."""
    elements, links = [], []
    for ln, t in body:
        s = t.strip()
        if m := re.match(r"^(artifact|node|component|container|database|rectangle)\s+(\w+)", s):
            elements.append({"type": m.group(1), "name": m.group(2), "line": ln})
        elif m := _LINK.match(s):
            links.append({"from": _strip(m.group(1)), "to": _strip(m.group(3)), "line": ln})
    d.data = {"elements": elements, "links": links}


_PARSERS = {"usecase": _parse_usecase, "class": _parse_class, "object": _parse_object,
            "state": _parse_state, "activity": _parse_activity, "sequence": _parse_sequence,
            "package": _parse_package, "component": _parse_boxes, "deployment": _parse_boxes,
            "container": _parse_boxes}


def parse_plantuml_file(text: str, path: str = "<view>") -> list[Diagram]:
    lines = text.splitlines()
    diagrams: list[Diagram] = []
    view, caption = "", ""
    i = 0
    while i < len(lines):
        t = lines[i]
        if m := _VIEW_HEADING.match(t):
            view = m.group(1)
        elif m := _CAPTION.match(t):
            caption = m.group(2).strip()
        elif m := _START.match(t):
            name, start = m.group(1) or f"Diagram@{i + 1}", i + 1
            body = []
            i += 1
            while i < len(lines) and not _END.match(lines[i]):
                body.append((i + 1, lines[i]))
                i += 1
            d = Diagram(name=name, kind=_guess_kind(name, [b for _, b in body]),
                        view=view, caption=caption, line=start,
                        source="\n".join(b for _, b in body))
            parser = _PARSERS.get(d.kind)
            if parser:
                parser(d, body)
            else:
                d.warn(start, "could not determine diagram type")
            diagrams.append(d)
        i += 1
    return diagrams
