"""The agent's tools.

Each tool = JSON schema (what the model sees) + a Python function (what runs).
Design rules taken from Claude Code (see how-claude-code-works, ch. 4/5/13):

* SAFE DEFAULTS     a tool is assumed to write and to be unsafe to run in
                    parallel unless it declares otherwise (read_only=True).
* READ BEFORE EDIT  edit_file / write_file refuse to touch an existing file the
                    agent has not read, or that changed on disk since it read it.
                    Enforced in code, not just asked for in the prompt.
* EXACT EDITS       edit_file replaces an exact string that must occur exactly
                    once (or replace_all=True). If the model "remembers" code
                    that is not there, the edit fails instead of corrupting the file.
* ERRORS ARE DATA   a refused or failed tool returns an error TEXT to the model,
                    so it can correct itself; the loop never crashes on it.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .sandbox import Sandbox, SandboxError, truncate

SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage", "__pycache__"}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., str]
    read_only: bool = False          # safe default: assume it writes

    def spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class ToolContext:
    sandbox: Sandbox
    read_state: dict = field(default_factory=dict)       # rel path -> mtime when last read/written by the agent
    todos: list = field(default_factory=list)
    on_event: Callable[[str, dict], None] = lambda kind, data: None
    files_written: set = field(default_factory=set)
    write_scope: list | None = None      # glob patterns this agent may write (None = whole workspace)
    protected: list = field(default_factory=list)   # glob patterns nobody in this context may write


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


# ====================================================================== tool functions
def _mark_known(ctx: ToolContext, full: str) -> None:
    ctx.read_state[ctx.sandbox.rel(full)] = os.path.getmtime(full)


def _check_scope(ctx: ToolContext, full: str) -> None:
    """Sub-agent isolation: each agent may only write its own files; protected files are read-only."""
    rel = ctx.sandbox.rel(full)
    if any(fnmatch.fnmatch(rel, p) for p in ctx.protected):
        raise SandboxError(f"'{rel}' is protected for your role (e.g. tests are locked for coders). "
                           f"If you believe it is wrong, explain why in your final report instead.")
    if ctx.write_scope is not None and not any(fnmatch.fnmatch(rel, p) for p in ctx.write_scope):
        raise SandboxError(f"'{rel}' is outside your write scope {ctx.write_scope}. Only change your own files.")


def _require_fresh_read(ctx: ToolContext, path: str, full: str) -> None:
    rel = ctx.sandbox.rel(full)
    if rel not in ctx.read_state:
        raise SandboxError(f"you must read_file '{path}' before modifying it (it already exists).")
    if os.path.getmtime(full) != ctx.read_state[rel]:
        raise SandboxError(f"'{path}' changed on disk since you read it. read_file it again first.")


def read_file(ctx: ToolContext, path: str, offset: int = 1, limit: int = 400) -> str:
    text = ctx.sandbox.read_text(path)
    full = ctx.sandbox.resolve(path)
    lines = text.replace("\r\n", "\n").split("\n")
    start = max(1, int(offset))
    chunk = lines[start - 1:start - 1 + int(limit)]
    _mark_known(ctx, full)
    body = "\n".join(f"{n:5d} | {l}" for n, l in enumerate(chunk, start))
    more = f"\n[... {len(lines) - (start - 1 + len(chunk))} more lines; use offset to read on]" \
        if start - 1 + len(chunk) < len(lines) else ""
    return f"{ctx.sandbox.rel(full)} ({len(lines)} lines)\n{body}{more}"


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    full = ctx.sandbox.resolve(path)
    _check_scope(ctx, full)
    existed = os.path.exists(full)
    if existed:
        _require_fresh_read(ctx, path, full)
    ctx.sandbox.write_text(path, content)
    _mark_known(ctx, full)
    ctx.files_written.add(ctx.sandbox.rel(full))
    n = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
    return f"{'Overwrote' if existed else 'Created'} {ctx.sandbox.rel(full)} ({n} lines)"


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def edit_file(ctx: ToolContext, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    full = ctx.sandbox.resolve(path)
    if not os.path.exists(full):
        raise SandboxError(f"file not found: {path}. Use write_file to create new files.")
    _check_scope(ctx, full)
    _require_fresh_read(ctx, path, full)
    if old_string == new_string:
        raise SandboxError("old_string and new_string are identical; nothing to change.")
    if not old_string:
        raise SandboxError("old_string is empty. Use write_file to replace a whole file.")
    raw = ctx.sandbox.read_text(path)
    crlf = "\r\n" in raw
    content = raw.replace("\r\n", "\n")                      # match on LF-normalised text
    old, new = old_string.replace("\r\n", "\n"), new_string.replace("\r\n", "\n")
    count = content.count(old)
    if count == 0 and content.translate(_QUOTES).count(old.translate(_QUOTES)) == 1:
        idx = content.translate(_QUOTES).index(old.translate(_QUOTES))   # curly-quote tolerant match
        old, count = content[idx:idx + len(old)], 1
    if count == 0:
        raise SandboxError(f"old_string not found in {path}. read_file again and copy the exact text "
                           f"(including indentation).")
    if count > 1 and not replace_all:
        raise SandboxError(f"old_string occurs {count} times in {path}. Add surrounding lines to make it unique, "
                           f"or set replace_all=true.")
    content = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    ctx.sandbox.write_text(path, content.replace("\n", "\r\n") if crlf else content)
    _mark_known(ctx, full)
    ctx.files_written.add(ctx.sandbox.rel(full))
    return f"Edited {ctx.sandbox.rel(full)}: replaced {count if replace_all else 1} occurrence(s)"


def list_dir(ctx: ToolContext, path: str = ".", depth: int = 2) -> str:
    base = ctx.sandbox.resolve(path)
    if not os.path.exists(base):
        return f"(folder '{path}' does not exist yet)"
    if not os.path.isdir(base):
        raise SandboxError(f"not a directory: {path}")
    out = []

    def walk(d, level):
        for name in sorted(os.listdir(d)):
            full = os.path.join(d, name)
            if os.path.isdir(full):
                out.append("  " * level + name + "/" + ("  (skipped)" if name in SKIP_DIRS else ""))
                if name not in SKIP_DIRS and level + 1 < depth:
                    walk(full, level + 1)
            else:
                out.append("  " * level + f"{name}  ({os.path.getsize(full)} B)")
            if len(out) > 300:
                return
    walk(base, 0)
    return "\n".join(out) or "(empty directory)"


def grep(ctx: ToolContext, pattern: str, path: str = ".", glob: str = "*") -> str:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise SandboxError(f"invalid regex: {e}") from None
    base = ctx.sandbox.resolve(path)
    hits = []
    for d, dirs, files in os.walk(base):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if not fnmatch.fnmatch(f, glob):
                continue
            full = os.path.join(d, f)
            try:
                with open(full, encoding="utf-8", errors="ignore") as fh:
                    for n, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{ctx.sandbox.rel(full)}:{n}: {line.rstrip()[:200]}")
                            if len(hits) >= 100:
                                return "\n".join(hits) + "\n[stopped at 100 matches]"
            except OSError:
                continue
    return "\n".join(hits) or "no matches"


def run_command(ctx: ToolContext, command: str, timeout: int = 120) -> str:
    res = ctx.sandbox.run(command, timeout)
    ctx.on_event("command", {"command": command, "exit_code": res.exit_code, "seconds": round(res.seconds, 1),
                             "timed_out": res.timed_out})
    return res.render()


def todo_write(ctx: ToolContext, todos: list) -> str:
    clean = []
    for t in todos:
        if not isinstance(t, dict) or "content" not in t:
            raise SandboxError("each todo needs 'content' and 'status' (pending|in_progress|done)")
        status = t.get("status", "pending")
        if status not in ("pending", "in_progress", "done"):
            raise SandboxError(f"invalid status '{status}'")
        clean.append({"content": str(t["content"])[:200], "status": status})
    if sum(t["status"] == "in_progress" for t in clean) > 1:
        raise SandboxError("only one todo may be in_progress at a time")
    ctx.todos[:] = clean
    ctx.on_event("todos", {"todos": clean})
    mark = {"pending": "[ ]", "in_progress": "[>]", "done": "[x]"}
    return "Todo list updated:\n" + "\n".join(f"{mark[t['status']]} {t['content']}" for t in clean)


# ====================================================================== registry
def build_tools(permission: str = "workspace-write") -> list[Tool]:
    """permission: 'read-only' (reviewer/explorer sub-agents) or 'workspace-write' (coder/tester)."""
    S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
    tools = [
        Tool("read_file", "Read a text file. Returns numbered lines. Read a file before editing it.",
             _obj({"path": S, "offset": {**I, "description": "first line (1-based)"},
                   "limit": {**I, "description": "max lines, default 400"}}, ["path"]), read_file, read_only=True),
        Tool("list_dir", "List files and folders (node_modules is skipped).",
             _obj({"path": S, "depth": I}, []), list_dir, read_only=True),
        Tool("grep", "Search file contents with a regular expression. Returns file:line: text.",
             _obj({"pattern": S, "path": S, "glob": {**S, "description": "file name filter, e.g. *.js"}},
                  ["pattern"]), grep, read_only=True),
        Tool("todo_write", "Replace your task list. Use it to plan multi-step work and mark progress.",
             _obj({"todos": {"type": "array", "items": _obj(
                 {"content": S, "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
                 ["content", "status"])}}, ["todos"]), todo_write, read_only=True),
    ]
    if permission == "workspace-write":
        tools += [
            Tool("write_file", "Create a new file or fully overwrite one you have read. Parent folders are created.",
                 _obj({"path": S, "content": S}, ["path", "content"]), write_file),
            Tool("edit_file", "Replace an exact string in a file you have read. old_string must match exactly "
                              "once (include surrounding lines) unless replace_all is true.",
                 _obj({"path": S, "old_string": S, "new_string": S, "replace_all": B},
                      ["path", "old_string", "new_string"]), edit_file),
            Tool("run_command", "Run ONE command in the project root without a shell. Allowed: node, "
                                "npm (install|ci|test|run|ls|init|pkg), npx (jest|electron-builder|eslint|prettier). "
                                "No pipes, &&, redirection or environment variables.",
                 _obj({"command": S, "timeout": {**I, "description": "seconds, default 120, max 600"}},
                      ["command"]), run_command),
        ]
    return tools


class ToolBox:
    """Holds the tools for one agent and executes calls by name."""

    def __init__(self, ctx: ToolContext, permission: str = "workspace-write"):
        self.ctx = ctx
        self.permission = permission
        self.tools = {t.name: t for t in build_tools(permission)}

    def specs(self) -> list[dict]:
        return [t.spec() for t in self.tools.values()]

    def is_read_only(self, name: str) -> bool:
        t = self.tools.get(name)
        return bool(t and t.read_only)

    def execute(self, name: str, arguments: str | dict) -> tuple[bool, str]:
        """Returns (ok, result_text). Never raises for model mistakes."""
        tool = self.tools.get(name)
        if tool is None:
            return False, f"ERROR: unknown tool '{name}'. Available: {', '.join(self.tools)}."
        try:
            args: Any = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            return False, f"ERROR: arguments for {name} are not valid JSON ({e}). Send a JSON object."
        props = tool.parameters["properties"]
        missing = [k for k in tool.parameters["required"] if k not in args]
        unknown = [k for k in args if k not in props]
        if missing or unknown:
            return False, (f"ERROR: {name} " + (f"missing {missing} " if missing else "") +
                           (f"unknown {unknown}" if unknown else "")).strip()
        try:
            return True, truncate(tool.func(self.ctx, **args))
        except SandboxError as e:
            return False, f"DENIED: {e}"
        except (TypeError, ValueError) as e:
            return False, f"ERROR: bad argument for {name}: {e}"
        except OSError as e:
            return False, f"ERROR: {type(e).__name__}: {e}"
