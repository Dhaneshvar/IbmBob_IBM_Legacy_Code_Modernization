"""Observability: lightweight span/trace recording.

Emits structured NDJSON spans to a log file and in-memory ring buffer.
Compatible with Loki label format so the frontend can render a Grafana-style
log stream without needing a real Loki server.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Generator, Optional
import uuid


@dataclass
class SpanRecord:
    trace_id: str
    span_id: str
    parent_id: Optional[str]
    name: str
    status: str          # ok | error | running
    start_ns: int
    end_ns: int = 0
    duration_ms: float = 0.0
    attrs: dict = field(default_factory=dict)
    error: Optional[str] = None
    ts: str = ""

    def to_log_line(self) -> str:
        """Loki-compatible NDJSON line."""
        return json.dumps({
            "ts": self.ts or datetime.now(timezone.utc).isoformat(),
            "trace_id": self.trace_id,
            "span": self.name,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
            "attrs": self.attrs,
            "error": self.error,
        })


class Tracer:
    """Thread-safe tracer with ring-buffer and optional file sink."""

    _RING_SIZE = 500

    def __init__(
        self,
        service: str = "lm-pipeline",
        log_path: Optional[str | Path] = None,
    ):
        self.service = service
        self.log_path = Path(log_path) if log_path else None
        self._ring: Deque[SpanRecord] = deque(maxlen=self._RING_SIZE)
        self._lock = threading.Lock()
        self._trace_id = _new_id()
        self._active: dict[str, SpanRecord] = {}
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────────

    def new_trace(self) -> str:
        self._trace_id = _new_id()
        return self._trace_id

    @contextmanager
    def span(
        self,
        name: str,
        /,
        parent_id: Optional[str] = None,
        **attrs: Any,
    ) -> Generator[SpanRecord, None, None]:
        """Record a duration span.

        ``name`` is positional-only on purpose: callers routinely splat
        arbitrary payload dicts into ``**attrs`` (progress events, request
        bodies), and a payload carrying a ``name`` key would otherwise collide
        with a positional-or-keyword parameter and raise
        ``TypeError: got multiple values for argument 'name'``. Any colliding
        key is preserved as ``attr.<key>`` rather than dropped.
        """
        attrs = _normalise_attrs(attrs)
        span_id = _new_id()
        rec = SpanRecord(
            trace_id=self._trace_id,
            span_id=span_id,
            parent_id=parent_id,
            name=name,
            status="running",
            start_ns=time.perf_counter_ns(),
            ts=datetime.now(timezone.utc).isoformat(),
            attrs={**attrs, "service": self.service},
        )
        self._emit(rec)
        try:
            yield rec
            rec.status = "ok"
        except Exception as exc:
            rec.status = "error"
            rec.error = str(exc)
            raise
        finally:
            rec.end_ns = time.perf_counter_ns()
            rec.duration_ms = (rec.end_ns - rec.start_ns) / 1_000_000
            rec.ts = datetime.now(timezone.utc).isoformat()
            self._emit(rec)

    def log(self, name: str, /, **attrs: Any) -> SpanRecord:
        """Emit a point event (not a duration span)."""
        attrs = _normalise_attrs(attrs)
        rec = SpanRecord(
            trace_id=self._trace_id,
            span_id=_new_id(),
            parent_id=None,
            name=name,
            status="ok",
            start_ns=time.perf_counter_ns(),
            end_ns=time.perf_counter_ns(),
            duration_ms=0,
            ts=datetime.now(timezone.utc).isoformat(),
            attrs={**attrs, "service": self.service},
        )
        self._emit(rec)
        return rec

    def recent(self, n: int = 100) -> list[dict]:
        """Return the most recent n span records as dicts."""
        with self._lock:
            records = list(self._ring)[-n:]
        return [asdict(r) for r in records]

    def recent_lines(self, n: int = 100) -> list[str]:
        """Return log lines (NDJSON) for the last n spans."""
        with self._lock:
            records = list(self._ring)[-n:]
        return [r.to_log_line() for r in records]

    # ── internals ─────────────────────────────────────────────────────────

    def _emit(self, rec: SpanRecord) -> None:
        with self._lock:
            self._ring.append(rec)
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(rec.to_log_line() + "\n")
            except OSError:
                pass


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


#: attribute names that would shadow a named parameter of ``span``/``log``.
_RESERVED_ATTRS = ("name", "parent_id", "self")


def _normalise_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Rename keys that would collide with a bound parameter of ``span``/``log``.

    ``span("parse", **{"name": "PAYROLL"})`` is legal Python once ``name`` is
    positional-only, but the payload must not silently overwrite the span name,
    so the key is moved to ``attr.<key>``.
    """
    out: dict[str, Any] = {}
    for key, val in attrs.items():
        out[f"attr.{key}" if key in _RESERVED_ATTRS else key] = val
    return out


# ── module-level default tracer ────────────────────────────────────────────
_default: Optional[Tracer] = None


def get_tracer() -> Tracer:
    global _default
    if _default is None:
        _default = Tracer(log_path=".lm/traces.ndjson")
    return _default


def configure_tracer(service: str = "lm-pipeline", log_path: Optional[str] = None) -> Tracer:
    global _default
    _default = Tracer(service=service, log_path=log_path or ".lm/traces.ndjson")
    return _default
