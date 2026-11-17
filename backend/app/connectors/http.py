"""Reusable REST connector with timeouts, error classification and exponential backoff scheduling."""

import json as _json
import logging
import os
import random
import time
from urllib.parse import urlsplit

import httpx

from app.connectors.egress import DEFAULT_PORTS, EgressDenied, EgressPolicy, get_policy
from app.connectors.ratelimit import LIMITERS, RateLimited
from app.observability import tracing
from app.observability.logging import log_event
from app.observability.metrics import METRICS
from app.observability.tracing import outbound_headers as _trace_headers

log =logging.getLogger("eaop.connector")

TRANSIENT, PERMANENT, MALFORMED = "transient", "permanent", "malformed"
OUTBOUND_RATE, OUTBOUND_BURST, OUTBOUND_MAX_WAIT = 50.0, 100, 2.0  # per tenant and upstream host: protects the upstream from a runaway loop, never throttles normal use


class ConnectorError(Exception):
    def __init__(self, message: str, kind: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after  # seconds the upstream asked us to wait (Retry-After), validated


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 300.0, jitter: bool = True) -> float:
    """Exponential backoff for the given 1-based attempt number."""
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    return random.uniform(delay / 2, delay) if jitter and delay else delay  # noqa: S311 - not crypto


def _parse_retry_after(value: str | None) -> float | None:
    """Retry-After as a number of seconds (HTTP-date forms are ignored: an unparseable value is no value)."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if 0 <= seconds < 86400 else None


MAX_RESPONSE_BYTES = 1024 * 1024
EGRESS_DENIED = "egress_denied"


class HttpConnector:
    """HTTP client for one tenant connector. Every request re-validates the destination against the server's
    egress policy and connects to the validated (pinned) address; redirects are never followed."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        tenant_slug: str | None = None,
        policy: EgressPolicy | None = None,
        tenant_id: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport
        self.tenant_slug = tenant_slug
        self.tenant_id = tenant_id
        self._policy = policy

    def request(
        self, method: str, path: str, *, json: dict | None = None, headers: dict[str, str] | None = None,
        raw: bool = False, max_bytes: int = 1024 * 1024
    ) -> dict | bytes:
        """JSON object by default; `raw=True` returns the body bytes (a CSV file) within `max_bytes` (at most 5 MiB)."""
        started = time.perf_counter()
        outcome = "ok"
        try:
            with tracing.span("connector.call", method=method, origin=urlsplit(self.base_url).netloc):
                return self._request(method, path, json=json, headers=headers, raw=raw,
                                     max_bytes=min(max_bytes, 5 * 1024 * 1024))
        except ConnectorError as exc:
            outcome = "denied" if exc.kind == PERMANENT and "destination not permitted" in str(exc) else exc.kind
            raise
        finally:
            elapsed = time.perf_counter() - started
            METRICS.incr("connector_calls_total", tenant=self.tenant_id, outcome=outcome)
            METRICS.observe("connector_seconds", elapsed, tenant=self.tenant_id)
            log_event(
                log,
                "connector.call",
                level=logging.INFO if outcome == "ok" else logging.WARNING,
                tenant_id=self.tenant_id,
                origin=self.base_url.split("//", 1)[-1].split("/", 1)[0],
                method=method,
                outcome=outcome,
                duration_ms=round(elapsed * 1000, 1),
            )

    def _request(
        self, method: str, path: str, *, json: dict | None = None, headers: dict[str, str] | None = None,
        raw: bool = False, max_bytes: int = 1024 * 1024
    ) -> dict | bytes:
        policy = self._policy or get_policy()
        try:
            target = policy.authorize(self.base_url, self.tenant_slug)
        except EgressDenied as exc:  # nothing is sent, so no credential can leak; never retried
            raise ConnectorError(f"destination not permitted: {exc.reason}", PERMANENT) from exc
        hdrs = dict(headers or {})
        hdrs.update(_trace_headers())
        hdrs["Host"] = f"{target.host}:{target.port}" if target.port != DEFAULT_PORTS[target.scheme] else target.host
        if self.api_key:
            hdrs["X-API-Key"] = self.api_key
        address = f"[{target.address}]" if ":" in target.address else target.address
        url = f"{target.scheme}://{address}:{target.port}{urlsplit(self.base_url).path.rstrip('/')}{path}"
        extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
        timeout = httpx.Timeout(self.timeout, connect=min(self.timeout, 3.0))
        try:  # outbound protection for every client (shared across processes when a database is configured): generous defaults, bounded wait
            LIMITERS.get(self.tenant_id or self.tenant_slug or "-", f"http:{target.host}:{target.port}", OUTBOUND_RATE, OUTBOUND_BURST).acquire(OUTBOUND_MAX_WAIT)
        except RateLimited as exc:
            METRICS.incr("connector_rate_limited_total", tenant=str(self.tenant_id) if self.tenant_id else None)
            raise ConnectorError("outbound rate limit reached; retry later", TRANSIENT, None, exc.retry_after) from exc
        try:
            with httpx.Client(timeout=timeout, transport=self._transport, follow_redirects=False) as client:
                with client.stream(method, url, json=json, headers=hdrs, extensions=extensions) as response:
                    status = response.status_code
                    retry_after = None
                    if status in (429, 503):
                        retry_after = _parse_retry_after(response.headers.get("retry-after"))
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ConnectorError(f"response from {path} exceeds the size limit", MALFORMED, status)
                        chunks.append(chunk)
                    content = b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise ConnectorError(f"timeout calling {path}", TRANSIENT) from exc
        except httpx.TransportError as exc:
            raise ConnectorError(f"network error calling {path}: {type(exc).__name__}", TRANSIENT) from exc
        if 300 <= status < 400:
            raise ConnectorError(f"redirect from {path} refused (redirects are never followed)", PERMANENT, status)
        if status in (408, 429) or status >= 500:
            raise ConnectorError(f"HTTP {status} from {path}", TRANSIENT, status, retry_after)
        if status >= 400:
            raise ConnectorError(f"HTTP {status} from {path}", PERMANENT, status)
        if raw:
            return content
        try:
            body = _json.loads(content)
        except ValueError as exc:
            raise ConnectorError(f"non-JSON response from {path}", MALFORMED, status) from exc
        if not isinstance(body, dict):
            raise ConnectorError(f"unexpected response shape from {path}", MALFORMED, status)
        return body


def resolve_secret(secret_ref: str | None) -> str | None:
    """Connector rows store only the NAME of an environment variable, never the secret."""
    return os.environ.get(secret_ref) if secret_ref else None
