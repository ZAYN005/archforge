"""Workspace sandbox: the safety layer between the model and the computer.

The model never touches the file system or the shell directly. It asks for a
tool, and every tool goes through this class. Four protections:

1. PATH JAIL      Every path is resolved to a real absolute path (following
                  symlinks and '..') and must lie inside the workspace root.
2. COMMAND POLICY ALLOW-list, not block-list: only `node`, `npm` (selected
                  sub-commands) and `npx` (selected packages). No shell is
                  used (shell=False), and shell metacharacters (& | ; > < ` $
                  % ^) are refused outright, so command chaining, redirection
                  and Windows .cmd argument injection are impossible.
3. CLEAN ENV      Child processes get a copy of the environment with every
                  KEY / TOKEN / SECRET / PASSWORD variable removed, so the
                  generated code can never read DEEPSEEK_API_KEY.
4. LIMITS         Timeout (whole process tree is killed), output truncated to
                  head + tail, file size caps.

Honest scope: this is a *policy* sandbox, not OS-level isolation. `node` may
run code the model wrote, and that code runs with the user's permissions.
What the policy guarantees: no secrets in the child env, no writes through
our tools outside the workspace, no shell tricks, no runaway processes.
(Claude Code itself uses regex/AST checks on a full shell; we choose an
allow-list because our task needs only three programs.)
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass

METACHARS = re.compile(r"[&|;<>`$%^\n\r]")
SECRET_ENV = re.compile(r"(?i)(key|token|secret|password|passwd|credential)")

DEFAULT_ALLOWED = {
    "node": None,                                            # any args (runs workspace JS)
    "npm": {"install", "i", "ci", "test", "t", "run", "ls", "init", "pkg", "audit", "--version", "-v"},
    "npx": {"jest", "electron-builder", "eslint", "prettier"},
}

INLINE_CODE_FLAGS = {"-e", "--eval", "-p", "--print", "-i", "--interactive", "-"}

MAX_READ_BYTES = 2_000_000
MAX_WRITE_BYTES = 400_000


class SandboxError(Exception):
    """A request the sandbox refuses. The message is shown to the model so it can adapt."""


@dataclass
class CommandResult:
    command: str
    exit_code: int | None
    output: str
    seconds: float
    timed_out: bool = False

    def render(self) -> str:
        status = "TIMED OUT" if self.timed_out else f"exit code {self.exit_code}"
        return f"$ {self.command}\n[{status}, {self.seconds:.1f}s]\n{self.output}"


def truncate(text: str, limit: int = 12_000) -> str:
    """Keep the beginning AND the end (errors and summaries are usually at the end)."""
    if len(text) <= limit:
        return text
    keep = limit // 2
    return f"{text[:keep]}\n\n[... {len(text) - 2 * keep} characters truncated ...]\n\n{text[-keep:]}"


class Sandbox:
    def __init__(self, root: str, allowed: dict | None = None, extra_programs: dict | None = None,
                 default_timeout: int = 120, max_timeout: int = 600, npm_registry: str | None = None,
                 extra_env: dict | None = None):
        os.makedirs(root, exist_ok=True)
        self.root = os.path.realpath(root)
        self.allowed = dict(DEFAULT_ALLOWED if allowed is None else allowed)
        self.extra_programs = extra_programs or {}            # name -> absolute path (used by tests)
        for name in self.extra_programs:
            self.allowed.setdefault(name, None)
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.npm_registry = npm_registry                      # e.g. https://registry.npmmirror.com in China
        self.extra_env = extra_env or {}

    # ------------------------------------------------------------ paths
    def resolve(self, path: str) -> str:
        if not isinstance(path, str) or not path.strip():
            raise SandboxError("path must be a non-empty string")
        p = path.strip().replace("\\", "/")
        if re.match(r"^[A-Za-z]:", p) and os.name != "nt":      # a Windows drive path on a non-Windows host
            raise SandboxError(f"path '{path}' is outside the workspace. Use paths relative to the project root.")
        full = os.path.realpath(p if os.path.isabs(p) else os.path.join(self.root, p))
        try:
            inside = os.path.commonpath([full, self.root]) == self.root
        except ValueError:                                     # different drives on Windows
            inside = False
        if not inside:
            raise SandboxError(f"path '{path}' is outside the workspace. Use paths relative to the project root.")
        return full

    def rel(self, full: str) -> str:
        return os.path.relpath(full, self.root).replace("\\", "/")

    def read_text(self, path: str) -> str:
        full = self.resolve(path)
        if not os.path.isfile(full):
            raise SandboxError(f"file not found: {path}")
        if os.path.getsize(full) > MAX_READ_BYTES:
            raise SandboxError(f"file too large to read ({os.path.getsize(full)} bytes)")
        with open(full, encoding="utf-8", errors="replace", newline="") as f:
            return f.read()

    def write_text(self, path: str, content: str) -> str:
        full = self.resolve(path)
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise SandboxError(f"content too large ({len(data)} bytes, max {MAX_WRITE_BYTES})")
        if "node_modules" in self.rel(full).split("/"):
            raise SandboxError("writing inside node_modules is not allowed")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
        return full

    # ------------------------------------------------------------ commands
    def check_command(self, command: str) -> list[str]:
        """Validate a command string and return the argv list. Raises SandboxError if refused."""
        if not isinstance(command, str) or not command.strip():
            raise SandboxError("empty command")
        if m := METACHARS.search(command):
            raise SandboxError(f"character {m.group()!r} is not allowed: no pipes, chaining, redirection or "
                               f"variables. Run one command per call.")
        try:
            argv = shlex.split(command.replace("\\", "/"))
        except ValueError as e:
            raise SandboxError(f"could not parse command: {e}") from None
        prog = os.path.basename(argv[0]).lower()
        prog = re.sub(r"\.(cmd|exe|bat)$", "", prog)
        if prog not in self.allowed:
            raise SandboxError(f"program '{argv[0]}' is not allowed. Allowed: {', '.join(sorted(self.allowed))}.")
        subs = self.allowed[prog]
        if subs is not None:
            first = next((a for a in argv[1:] if not a.startswith("-") or a in subs), None)
            if first is None or first not in subs:
                raise SandboxError(f"'{prog} {first or ''}' is not allowed. Allowed: {prog} {' | '.join(sorted(subs))}.")
        for a in argv[1:]:                                     # path-like args must stay inside the workspace
            if a.startswith(("/", "..")) or re.match(r"^[A-Za-z]:", a):
                if not a.startswith("--"):
                    self.resolve(a)
        if prog == "node":                                      # node may run FILES only, never inline code
            for x in argv[1:]:
                if x in INLINE_CODE_FLAGS or x.split("=")[0] in INLINE_CODE_FLAGS:
                    raise SandboxError(f"'node {x}' (inline code) is not allowed. Write a file in your scope and "
                                       f"run it, or use the file tools.")
        argv[0] = prog
        return argv

    def _executable(self, prog: str) -> str:
        if prog in self.extra_programs:
            return self.extra_programs[prog]
        exe = shutil.which(prog)                               # on Windows finds npm.cmd / node.exe via PATHEXT
        if not exe:
            raise SandboxError(f"'{prog}' is not installed or not on PATH")
        return exe

    def child_env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
        env.update(CI="true", FORCE_COLOR="0", NO_COLOR="1", npm_config_yes="true",
                   npm_config_fund="false", npm_config_audit="false", npm_config_update_notifier="false",
                   ELECTRON_SKIP_BINARY_DOWNLOAD="1")          # tests never need the 100 MB Electron binary
        if self.npm_registry:
            env["npm_config_registry"] = self.npm_registry
        env.update(self.extra_env)
        return env

    def run(self, command: str, timeout: int | None = None) -> CommandResult:
        argv = self.check_command(command)
        argv[0] = self._executable(argv[0])
        t = max(1, min(int(timeout or self.default_timeout), self.max_timeout))
        kwargs = dict(cwd=self.root, env=self.child_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      stdin=subprocess.DEVNULL)
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        t0 = time.time()
        proc = subprocess.Popen(argv, **kwargs)
        try:
            out, _ = proc.communicate(timeout=t)
            timed_out = False
        except subprocess.TimeoutExpired:
            self._kill_tree(proc)
            out, _ = proc.communicate()
            timed_out = True
        text = (out or b"").decode("utf-8", errors="replace")
        return CommandResult(command, None if timed_out else proc.returncode, truncate(text),
                             time.time() - t0, timed_out)

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """npm starts child processes; kill the whole tree, not just npm."""
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            proc.kill()
