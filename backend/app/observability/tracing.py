"""Lightweight trace context (W3C `traceparent` compatible) without an OpenTelemetry SDK or collector.

One trace id follows a unit of work across the API request, the durable job or outbox event it creates, the worker run
and the outbound connector call, and is written into every structured log line. It is NOT a full tracing system: there
are no spans, no sampling and no exporter. A trace id is an opaque correlation value, never a secret.

How the id travels:
  * API request: a valid incoming `traceparent` supplies it; otherwise it is derived from the correlation id
    (`X-Correlation-ID` or a fresh UUID).
  * Durable jobs: the correlation id is already stored on the job; the worker derives the same trace id from it.
  * Outbox events: the trace id is stored in the event payload when the event is enqueued.
  * Outbound HTTP: `traceparent` is added with a fresh span id so a receiving service can join the trace.
"""

import contextvars
import hashlib
import logging
import re
import secrets
import time
from contextlib import contextmanager

_TRACE: contextvars.ContextVar[str | None] = contextvars.ContextVar("eaop_trace_id", default=None)
_SPAN: contextvars.ContextVar[str | None] = contextvars.ContextVar("eaop_span_id", default=None)
log = logging.getLogger("eaop.trace")
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def parse_traceparent(value: str | None) -> str | None:
    """Trace id from a valid version-00 traceparent header, else None (all-zero ids are invalid)."""
    match = _TRACEPARENT.match((value or "").strip().lower())
    if not match or match.group(1) == "0" * 32 or match.group(2) == "0" * 16:
        return None
    return match.group(1)


def trace_id_for(correlation_id: str | None) -> str | None:
    """Stable 32-hex trace id for a correlation id: the id itself when it already is one, else its SHA-256 prefix."""
    if not correlation_id:
        return None
    lowered = str(correlation_id).lower()
    if _HEX32.match(lowered) and lowered != "0" * 32:
        return lowered
    return hashlib.sha256(lowered.encode()).hexdigest()[:32]


def new_trace_id() -> str:
    return secrets.token_hex(16)


def current() -> str | None:
    return _TRACE.get()


@contextmanager
def use_trace(trace_id: str | None):
    """Make `trace_id` current for the block (no-op when None); always restored afterwards."""
    token = _TRACE.set(trace_id) if trace_id else None
    try:
        yield trace_id
    finally:
        if token is not None:
            _TRACE.reset(token)


def set_current(trace_id: str | None) -> contextvars.Token:
    return _TRACE.set(trace_id)


def reset(token: contextvars.Token) -> None:
    _TRACE.reset(token)


def current_span() -> str | None:
    return _SPAN.get()


@contextmanager
def span(name: str, **attributes):
    """A span: a named, timed unit of work inside the current trace, emitted as ONE structured log event (`event=span`) when it ends, with `span_id`, `parent_span_id`, `duration_ms`,
    `status` (ok or error) and the attributes the caller adds to the yielded dict. Nested spans link through the context. Without a current trace nothing is emitted. This is the
    OpenTelemetry data model written as log events, not the OpenTelemetry SDK: there is no sampling and no exporter (see docs/operations/observability.md). Attributes must be technical
    identifiers and numbers only (never document text, user input or credentials)."""
    trace_id = _TRACE.get()
    if not trace_id:
        yield {}
        return
    span_id, parent = secrets.token_hex(8), _SPAN.get()
    token = _SPAN.set(span_id)
    attrs: dict = dict(attributes)
    started = time.perf_counter()
    status = "ok"
    try:
        yield attrs
    except BaseException as exc:
        status = "error"
        attrs.setdefault("error_class", type(exc).__name__)
        raise
    finally:
        _SPAN.reset(token)
        log.info("span", extra={"event": "span", "trace_id": trace_id, "span_name": name, "span_id": span_id, "parent_span_id": parent,
                                "duration_ms": round((time.perf_counter() - started) * 1000, 2), "status": status, **{f"attr_{k}": v for k, v in attrs.items()}})


def outbound_headers() -> dict[str, str]:
    """`traceparent` for an outbound call: the current span (if any) is the parent, so the receiver can attach its own work to it; empty when no trace is current."""
    trace_id = _TRACE.get()
    return {"traceparent": f"00-{trace_id}-{_SPAN.get() or secrets.token_hex(8)}-01"} if trace_id else {}
