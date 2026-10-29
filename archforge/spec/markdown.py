"""Line-aware Markdown parser.

Turns a Markdown file into simple building blocks, each remembering the
LINE NUMBER it came from and the SECTION it sits in:

  headings     # A. Executive Summary
  tables       | a | b |
  code blocks  ```yml ... ```
  bullets      * GameComponent: responsible for ...
  lines        any other non-empty text line ("Chosen architectural style: Microservices")

Why line numbers? Every fact in the IR and every lint finding points back to
`file:line`, so a human (or the professor) can verify it in seconds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*```\s*([\w+-]*)\s*$")
_BULLET = re.compile(r"^\s*(?:[*\-+]|\d+\.)\s+(.*\S)\s*$")


@dataclass
class Item:
    kind: str                 # "heading" | "table" | "code" | "bullet" | "line"
    line: int                 # 1-based line number where the item starts
    section: list[str]        # heading path, e.g. ["D. Detailed Technical Design", "GameComponent"]
    text: str = ""            # heading title / bullet text / line text / code content
    lang: str = ""            # code block language
    level: int = 0            # heading level
    header: list[str] = field(default_factory=list)       # table header cells
    rows: list[list[str]] = field(default_factory=list)   # table body rows
    row_lines: list[int] = field(default_factory=list)    # line number of each row

    def in_section(self, pattern: str) -> bool:
        """True if any heading in this item's path matches the regex (case-insensitive)."""
        return any(re.search(pattern, s, re.I) for s in self.section)


@dataclass
class MarkdownDoc:
    path: str
    text: str
    items: list[Item]

    def where(self, item_or_line) -> str:
        line = item_or_line if isinstance(item_or_line, int) else item_or_line.line
        return f"{self.path}:{line}"

    def find(self, kind: str | None = None, section: str | None = None) -> list[Item]:
        return [i for i in self.items
                if (kind is None or i.kind == kind) and (section is None or i.in_section(section))]

    def grep(self, pattern: str) -> list[tuple[int, str]]:
        """All (line_number, line_text) whose text matches the regex."""
        rx = re.compile(pattern)
        return [(n, t) for n, t in enumerate(self.text.splitlines(), 1) if rx.search(t)]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_markdown(text: str, path: str = "<doc>") -> MarkdownDoc:
    lines = text.splitlines()
    items: list[Item] = []
    stack: list[tuple[int, str]] = []          # (level, title) of open headings
    i = 0

    def section() -> list[str]:
        return [t for _, t in stack]

    while i < len(lines):
        raw = lines[i]
        n = i + 1

        # --- fenced code block: swallow everything until the closing fence ---
        m = _FENCE.match(raw)
        if m:
            lang, body, start = m.group(1).lower(), [], n + 1
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            items.append(Item("code", start, section(), "\n".join(body), lang=lang))
            i += 1                                 # skip closing fence
            continue

        # --- heading: update the section stack ---
        m = _HEADING.match(raw)
        if m:
            level, title = len(m.group(1)), m.group(2)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            items.append(Item("heading", n, section(), title, level=level))
            i += 1
            continue

        # --- table: consecutive lines starting with '|' ---
        if raw.lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append((i + 1, lines[i]))
                i += 1
            header = _cells(block[0][1])
            body = [(ln, _cells(t)) for ln, t in block[1:]
                    if not re.fullmatch(r"[\s|:\-]+", t)]          # drop the |---|---| separator
            items.append(Item("table", n, section(), header=header,
                              rows=[r for _, r in body], row_lines=[ln for ln, _ in body]))
            continue

        # --- bullet or plain line ---
        m = _BULLET.match(raw)
        if m:
            items.append(Item("bullet", n, section(), m.group(1)))
        elif raw.strip():
            items.append(Item("line", n, section(), raw.strip()))
        i += 1

    return MarkdownDoc(path, text, items)
