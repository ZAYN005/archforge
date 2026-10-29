"""The agent loop - the heart of a Claude-Code-style agent.

    messages = [system, task]
    repeat:
        reply = LLM(messages, tools)
        if reply has no tool calls:  -> done, reply.content is the final report
        else: run each tool, append results, continue

Extra machinery around that core, each mapped to a Claude Code mechanism:
  * batching       consecutive read-only tool calls run in parallel threads;
                   anything that writes runs alone, in order (safe default).
  * microcompact   when the context grows past a threshold, old large tool
                   results are replaced by a one-line stub - no API call needed.
  * stuck guard    the same failing call 3x in a row -> a nudge is injected.
  * limits         max turns, budget guard (from llm.py), all errors become
                   tool results the model can react to.
  * events         every turn / tool call / result goes to the event log.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..llm import BudgetExceeded, estimate_tokens
from ..redact import redact
from .tools import ToolBox


@dataclass
class AgentResult:
    status: str                      # done | max_turns | budget | error
    final_text: str
    turns: int
    tool_calls: int
    failed_calls: int
    files_written: list = field(default_factory=list)
    messages: list = field(default_factory=list, repr=False)


def _assistant_dict(msg) -> dict:
    """Serialise the model's reply ourselves (SDK-independent). Keeps reasoning_content (DeepSeek rule)."""
    d: dict = {"role": "assistant", "content": msg.content or ""}
    rc = getattr(msg, "reasoning_content", None)
    if rc:
        d["reasoning_content"] = rc
    if msg.tool_calls:
        d["tool_calls"] = [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                           for tc in msg.tool_calls]
    return d


def _short(s: str, n: int = 160) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


class AgentLoop:
    def __init__(self, llm, toolbox: ToolBox, system_prompt: str, *, role: str = "agent",
                 max_turns: int = 30, thinking: bool = False, effort: str = "high",
                 compact_at_tokens: int = 48_000, keep_recent_results: int = 6, max_tokens: int = 16000):
        self.llm = llm
        self.tools = toolbox
        self.system_prompt = system_prompt
        self.role = role
        self.max_turns = max_turns
        self.thinking = thinking
        self.effort = effort
        self.compact_at = compact_at_tokens
        self.keep_recent = keep_recent_results
        self.max_tokens = max_tokens
        self.events = llm.events

    # ------------------------------------------------------------ context management
    def microcompact(self, messages: list[dict]) -> int:
        """Replace old, large tool results with a stub. Returns characters freed.

        Trade-off: editing an old message breaks the prompt-cache prefix from that point,
        so we only do it when over the threshold, and clear in one go (cache rebuilds once)."""
        if estimate_tokens(messages) < self.compact_at:
            return 0
        tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool"]
        freed = 0
        for i in tool_idx[:-self.keep_recent] if self.keep_recent else tool_idx:
            c = messages[i]["content"]
            if len(c) > 400 and not c.startswith("[cleared"):
                messages[i]["content"] = (f"[cleared to save context: earlier result of {len(c)} chars. "
                                          f"Run the tool again if you still need it.]")
                freed += len(c)
        if freed:
            self.events.emit("compact", role=self.role, chars_freed=freed)
        return freed

    # ------------------------------------------------------------ tool execution
    def _run_calls(self, calls) -> list[tuple[str, bool, str]]:
        """Run tool calls; consecutive read-only calls share a parallel batch. Results keep call order."""
        results: list = [None] * len(calls)
        batch: list[int] = []

        def flush():
            if not batch:
                return
            with ThreadPoolExecutor(max_workers=4) as pool:
                outs = list(pool.map(lambda j: self.tools.execute(calls[j].function.name,
                                                                  calls[j].function.arguments), batch))
            for j, (ok, text) in zip(batch, outs):
                results[j] = (calls[j].id, ok, text)
            batch.clear()

        for j, tc in enumerate(calls):
            if self.tools.is_read_only(tc.function.name):
                batch.append(j)
            else:
                flush()
                ok, text = self.tools.execute(tc.function.name, tc.function.arguments)
                results[j] = (tc.id, ok, text)
        flush()
        return results

    # ------------------------------------------------------------ main loop
    def run(self, task: str) -> AgentResult:
        messages: list[dict] = [{"role": "system", "content": self.system_prompt},
                                {"role": "user", "content": task}]
        n_calls = n_failed = 0
        last_failures: list[str] = []
        self.events.emit("agent_start", role=self.role, task=_short(task, 300),
                         tools=list(self.tools.tools), permission=self.tools.permission)

        for turn in range(1, self.max_turns + 1):
            self.microcompact(messages)
            try:
                msg, usage, cost = self.llm.chat(messages, role=self.role, tools=self.tools.specs(),
                                                 thinking=self.thinking, effort=self.effort,
                                                 max_tokens=self.max_tokens)
            except BudgetExceeded as e:
                self.events.emit("agent_stop", role=self.role, status="budget", reason=str(e), turns=turn)
                return self._result("budget", str(e), turn, n_calls, n_failed, messages)
            except Exception as e:     # API error after retries
                self.events.emit("agent_stop", role=self.role, status="error", reason=redact(str(e)), turns=turn)
                return self._result("error", redact(str(e)), turn, n_calls, n_failed, messages)

            messages.append(_assistant_dict(msg))
            if msg.content and msg.tool_calls:
                self.events.emit("agent_say", role=self.role, turn=turn, text=_short(msg.content, 300))
            if not msg.tool_calls:
                self.events.emit("agent_stop", role=self.role, status="done", turns=turn,
                                 final=_short(msg.content or "", 500))
                return self._result("done", msg.content or "", turn, n_calls, n_failed, messages)

            for tc in msg.tool_calls:
                self.events.emit("tool_call", role=self.role, turn=turn, tool=tc.function.name,
                                 args=_short(tc.function.arguments, 200))
            for (call_id, ok, text), tc in zip(self._run_calls(msg.tool_calls), msg.tool_calls):
                n_calls += 1
                n_failed += 0 if ok else 1
                messages.append({"role": "tool", "tool_call_id": call_id, "content": text})
                self.events.emit("tool_result", role=self.role, turn=turn, tool=tc.function.name, ok=ok,
                                 chars=len(text), preview=_short(text, 200))
                # stuck guard: the same failing call three times in a row
                sig = f"{tc.function.name}:{tc.function.arguments}"
                last_failures = (last_failures + [sig])[-3:] if not ok else []
                if len(last_failures) == 3 and len(set(last_failures)) == 1:
                    messages.append({"role": "user", "content":
                                     "You have made the same failing call 3 times. Stop repeating it: read the "
                                     "error, inspect the files, and try a different approach."})
                    self.events.emit("stuck_nudge", role=self.role, turn=turn, tool=tc.function.name)
                    last_failures = []

        # wrap-up turn: one last call WITHOUT tools, so the agent still delivers its report / verdict
        final = "Stopped: reached the turn limit."
        messages.append({"role": "user", "content": "You have reached the turn limit. Do not call any tools. "
                                                    "Give your final answer now, in the format your role requires."})
        try:
            msg, _, _ = self.llm.chat(messages, role=self.role, tools=None, thinking=False,
                                      max_tokens=self.max_tokens)
            final = msg.content or final
            messages.append(_assistant_dict(msg))
        except Exception as e:      # budget or API error: keep the default text
            self.events.emit("wrapup_failed", role=self.role, reason=redact(str(e))[:200])
        self.events.emit("agent_stop", role=self.role, status="max_turns", turns=self.max_turns,
                         final=_short(final, 500))
        return self._result("max_turns", final, self.max_turns, n_calls, n_failed, messages)

    def _result(self, status, text, turns, n_calls, n_failed, messages) -> AgentResult:
        return AgentResult(status, text, turns, n_calls, n_failed,
                           sorted(self.tools.ctx.files_written), messages)
