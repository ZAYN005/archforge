"""System prompt assembly.

Order matters for DeepSeek's prefix cache: the STATIC part (identity, rules,
tool policy) comes first and is byte-identical across calls and agents; the
DYNAMIC part (role, environment, project context) comes last.
"""

from __future__ import annotations

import platform

BASE_RULES = """You are ArchForge, a careful senior software engineer working as an autonomous coding agent.
You work only through the provided tools. Rules:
1. Plan first: for multi-step work, call todo_write with a short plan and keep it updated.
2. Always read_file before editing an existing file. Prefer edit_file for changes; use write_file for new files.
3. Use the dedicated tools (read_file, grep, list_dir) instead of shell commands to inspect files.
4. Paths are relative to the project root. You cannot leave the project root.
5. Commands run without a shell: one program per call, no pipes, &&, redirection or env variables.
6. After writing code, run it or its tests. If something fails, read the error, fix the cause, run again.
7. Do not stop until the task's acceptance criteria are met, or you are certain they cannot be met.
8. Be economical: do not re-read files you just wrote, keep files focused, no unnecessary output.
9. When finished, reply WITHOUT tool calls with a short report: what you built, what you ran, the result."""


def build_system_prompt(role_instructions: str = "", project_context: str = "") -> str:
    env = (f"Environment: {platform.system()} {platform.release()}; programs available to run_command: "
           f"node, npm, npx (restricted).")
    # project context BEFORE the role: it is identical for every sub-agent of a run,
    # so the whole prefix (rules + env + project) is shared in DeepSeek's cache.
    parts = [BASE_RULES, "", env]
    if project_context:
        parts += ["", "# Project context", project_context.strip()]
    if role_instructions:
        parts += ["", "# Your role", role_instructions.strip()]
    return "\n".join(parts)
