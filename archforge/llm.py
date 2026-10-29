"""DeepSeek client wrapper: one place where every LLM call goes through.

Responsibilities:
  1. Budget guard  - refuse to START a call that could push spend past the limit,
                     and stop the run immediately once the limit is reached.
  2. Cost meter    - exact token + CNY/USD accounting per call and per role
                     (Architect / Coder / Tester / Reviewer), using cache hit/miss.
  3. Retries       - transient errors (network, 429, 5xx) are retried with
                     exponential backoff; real errors (400, 401) fail fast.
  4. Thinking mode - per call: on/off and effort. Thinking costs output tokens,
                     so cheap mechanical steps run with it off.
  5. Logging       - one `llm_call` event per call (tokens, cost, latency, cache hit rate).

Prompt caching: DeepSeek caches automatically on the server. A request whose
beginning (prefix) matches an earlier request is billed at the "cache hit"
price (~30x cheaper). We can't switch it on - we can only *design for it*:
keep the big stable part (system prompt + spec IR) FIRST and identical across
calls, and put the changing part (the current task) LAST.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from openai import (APIConnectionError, APITimeoutError, InternalServerError,
                    OpenAI, RateLimitError)

from . import pricing
from .config import Settings
from .events import EventLog
from .redact import redact

RETRYABLE = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)


class BudgetExceeded(RuntimeError):
    """Raised when a call would exceed (or has exceeded) the token budget."""


class RunCancelled(BudgetExceeded):
    """Raised when the user presses Stop. Subclass of BudgetExceeded so every layer stops the same clean way."""


class MissingAPIKey(RuntimeError):
    pass


@dataclass
class CostMeter:
    budget_cny: float
    spent_cny: float = 0.0
    calls: int = 0
    usage: pricing.Usage = field(default_factory=pricing.Usage)
    by_role: dict = field(default_factory=dict)

    def add(self, role: str, u: pricing.Usage, cost: float) -> None:
        self.calls += 1
        self.spent_cny += cost
        for tgt in (self.usage, self.by_role.setdefault(role, pricing.Usage())):
            tgt.cache_hit += u.cache_hit
            tgt.cache_miss += u.cache_miss
            tgt.output += u.output
            tgt.reasoning += u.reasoning

    @property
    def remaining_cny(self) -> float:
        return self.budget_cny - self.spent_cny

    def check_before_call(self, estimated_cny: float) -> None:
        if self.spent_cny + estimated_cny > self.budget_cny:
            raise BudgetExceeded(
                f"Budget guard: spent CNY {self.spent_cny:.4f}, next call estimated CNY {estimated_cny:.4f}, "
                f"limit CNY {self.budget_cny:.4f}. Stopping before the limit is crossed.")


def estimate_tokens(messages: list[dict], tools: list | None = None) -> int:
    """Cheap, deliberately pessimistic estimate (~3 chars per token; real is ~3.5-4 for English/code)."""
    chars = sum(len(str(m.get("content") or "")) + len(str(m.get("reasoning_content") or ""))
                for m in messages)
    chars += len(str(tools or ""))
    return chars // 3 + 50


def message_to_dict(msg: Any) -> dict:
    """Convert an SDK response message into a dict we can append to `messages`.

    IMPORTANT (DeepSeek rule): when `tools` are used in thinking mode, the
    assistant's `reasoning_content` must be sent back on later turns,
    otherwise the API answers 400. So we keep it.
    """
    d = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else dict(msg)
    rc = getattr(msg, "reasoning_content", None)
    if rc is not None:
        d["reasoning_content"] = rc
    for junk in ("refusal", "annotations", "audio", "function_call"):
        d.pop(junk, None)
    return d


class LLMClient:
    def __init__(self, settings: Settings, events: EventLog | None = None,
                 meter: CostMeter | None = None, client: Any = None, cancel: Any = None):
        if not settings.has_key() and client is None:
            raise MissingAPIKey("No DeepSeek API key. Set DEEPSEEK_API_KEY or enter it in the GUI.")
        self.s = settings
        self.events = events or EventLog(path=None)
        self.meter = meter or CostMeter(budget_cny=settings.budget_cny)
        self.cancel = cancel                 # threading.Event set by the GUI's Stop button
        # max_retries=0: we do retries ourselves so every attempt is logged and visible.
        self._client = client or OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                                        timeout=settings.request_timeout_s, max_retries=0)

    # ------------------------------------------------------------------ #
    def chat(self, messages: list[dict], *, role: str = "main", tools: list | None = None,
             thinking: bool = False, effort: str = "high", max_tokens: int = 8192,
             json_mode: bool = False, model: str | None = None):
        """Send one chat request. Returns (message, Usage, cost_cny)."""
        model = model or self.s.model

        # ---- 1. budget guard (before spending anything) ----
        _, miss_p, out_p = pricing.price_table(model, peak=True)      # worst-case prices
        reserve_out = min(max_tokens, 4000 if not thinking else 8000)  # expected output, not max
        est = (estimate_tokens(messages, tools) * miss_p + reserve_out * out_p) / 1_000_000
        if self.cancel is not None and self.cancel.is_set():
            raise RunCancelled("Run cancelled by the user.")
        self.meter.check_before_call(est)

        kwargs: dict[str, Any] = dict(model=model, messages=messages, max_tokens=max_tokens)
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if thinking:
            kwargs["reasoning_effort"] = effort
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        # ---- 2. call with retries ----
        attempt, t0 = 0, time.time()
        while True:
            attempt += 1
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except RETRYABLE as e:
                if attempt > self.s.max_retries:
                    self.events.emit("llm_error", role=role, error=redact(str(e)), attempts=attempt)
                    raise
                wait = 2 ** (attempt - 1)
                self.events.emit("llm_retry", role=role, attempt=attempt, wait_s=wait,
                                 error=type(e).__name__)
                time.sleep(wait)
            except Exception as e:   # 400/401/etc: retrying will not help
                self.events.emit("llm_error", role=role, error=redact(str(e)), attempts=attempt)
                raise

        # ---- 3. account for cost ----
        usage = pricing.Usage.from_api(resp.usage)
        cost = pricing.cost_cny(model, usage, mode=self.s.pricing_mode)
        self.meter.add(role, usage, cost)
        msg = resp.choices[0].message
        self.events.emit(
            "llm_call", role=role, model=model, thinking=thinking,
            latency_s=round(time.time() - t0, 2), attempts=attempt,
            finish_reason=resp.choices[0].finish_reason,
            tokens={"cache_hit": usage.cache_hit, "cache_miss": usage.cache_miss,
                    "output": usage.output, "reasoning": usage.reasoning},
            cache_hit_rate=round(usage.hit_rate, 3),
            cost_cny=round(cost, 6), spent_cny=round(self.meter.spent_cny, 6),
            budget_cny=round(self.meter.budget_cny, 4),
            tool_calls=[tc.function.name for tc in (msg.tool_calls or [])],
            preview=(msg.content or "")[:200],
        )

        # ---- 4. hard stop once the budget is used up ----
        if self.meter.spent_cny >= self.meter.budget_cny:
            raise BudgetExceeded(f"Budget reached: CNY {self.meter.spent_cny:.4f} of CNY {self.meter.budget_cny:.4f}.")
        return msg, usage, cost
