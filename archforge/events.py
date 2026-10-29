"""Structured event log.

Every important step of a run is one JSON object on one line of
`events.jsonl` (the "JSON Lines" format). Why:
  - It is the single source of truth: the GUI's live panel, the cost meter,
    the final report and the video demo all read the same events.
  - Append-only + one line per event = a crash never corrupts earlier events.
  - Every event goes through `redact_obj()` before it touches the disk, so the
    API key cannot end up in the log even if some code passes it by mistake.

Other parts of the program can `subscribe()` a callback (the GUI does this)
to receive events live, without reading the file.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Callable

from .redact import redact_obj

Subscriber = Callable[[dict], None]


class EventLog:
    def __init__(self, path: str | None = "runs/events.jsonl", run_id: str | None = None):
        self.path = path
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self._seq = 0
        self._lock = threading.Lock()
        self._subscribers: list[Subscriber] = []
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    def emit(self, kind: str, **data: Any) -> dict:
        with self._lock:
            self._seq += 1
            event = redact_obj({
                "ts": round(time.time(), 3),
                "run_id": self.run_id,
                "seq": self._seq,
                "kind": kind,
                **data,
            })
            if self.path:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception:
                pass   # a broken GUI callback must never crash the agent
        return event
