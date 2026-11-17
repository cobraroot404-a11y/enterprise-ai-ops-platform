"""Resource protection: request-size limits and bounded concurrency for expensive endpoints.

Request-size limits are per request. The concurrency caps (AI inference, document ingestion) are shared by every API process through PostgreSQL leases (migrations 0016 and 0017) when a
shared key is set and the database is reachable; otherwise they are enforced per process by a semaphore (protection is reduced to "per process", never removed).
Fairness between tenants: a tenant may hold at most `tenant_limit` of a pool's slots at once (default: all but one when the pool has more than one slot), so one tenant's long requests
cannot occupy the whole pool. Rejections and fallbacks are counted (`concurrency_rejected_total`, `concurrency_fallback_total`).
"""
import json
import threading
import time
from contextlib import contextmanager

from app.core.errors import AppError
from app.observability.metrics import METRICS


class ConcurrencyLimiter:
    """At most `limit` concurrent holders; further callers wait briefly, then get 429 + Retry-After."""

    LEASE_TTL_SECONDS = 330  # longer than the longest request (model timeout 240 s): a crashed holder frees its slot when this expires

    def __init__(self, name: str, limit: int, wait_seconds: float, shared_key: str | None = None, tenant_limit: int | None = None):
        self.name, self.limit, self.wait_seconds, self.shared_key = name, limit, wait_seconds, shared_key
        self.tenant_limit = min(limit, tenant_limit) if tenant_limit else (limit - 1 if limit > 1 else limit)
        self._sem = threading.BoundedSemaphore(limit)
        self._tenant_lock = threading.Lock()
        self._tenant_counts: dict[str, int] = {}

    def _busy(self, reason: str) -> AppError:
        METRICS.incr("concurrency_rejected_total", pool=self.shared_key or self.name, reason=reason)
        return AppError(f"The server is busy with other {self.name} requests; retry shortly", code="server_busy", status_code=429, retry_after=5)

    def _acquire(self, store, key: str, limit: int, deadline: float):
        """A lease id, or None when the pool stayed full until the deadline. Raises StoreUnavailable."""
        while True:
            lease = store.lease_acquire(key, limit, self.LEASE_TTL_SECONDS)
            if lease is not None or time.monotonic() >= deadline:
                return lease
            time.sleep(0.05)

    def _release(self, leases) -> None:
        from app.connectors.ratelimit import LIMITERS, StoreUnavailable

        store = LIMITERS.store
        for lease in leases:
            try:
                if store is not None:
                    store.lease_release(lease)
            except StoreUnavailable:
                pass  # the lease expires on its own

    @contextmanager
    def _local(self, tenant: str | None):
        """Per-process enforcement (no shared key, or the database is unreachable): the same two caps, in memory."""
        if tenant is not None:
            with self._tenant_lock:
                if self._tenant_counts.get(tenant, 0) >= self.tenant_limit:
                    raise self._busy("tenant_share")
                self._tenant_counts[tenant] = self._tenant_counts.get(tenant, 0) + 1
        try:
            if not self._sem.acquire(timeout=self.wait_seconds):
                raise self._busy("pool_full")
            try:
                yield
            finally:
                self._sem.release()
        finally:
            if tenant is not None:
                with self._tenant_lock:
                    self._tenant_counts[tenant] -= 1
                    if self._tenant_counts[tenant] <= 0:
                        self._tenant_counts.pop(tenant, None)

    @contextmanager
    def slot(self, tenant_id=None):
        """Hold one slot. With `tenant_id`, the tenant's own share is checked first, then the pool. Shared across API processes when possible, otherwise per process."""
        from app.connectors.ratelimit import LIMITERS, StoreUnavailable

        tenant = str(tenant_id) if tenant_id is not None else None
        store = LIMITERS.usable_store() if self.shared_key else None
        if store is None:
            with self._local(tenant):
                yield
            return
        deadline, held = time.monotonic() + self.wait_seconds, []
        try:
            if tenant is not None and self.tenant_limit < self.limit:
                lease = self._acquire(store, f"{self.shared_key}:tenant:{tenant}", self.tenant_limit, deadline)
                if lease is None:
                    raise self._busy("tenant_share")
                held.append(lease)
            lease = self._acquire(store, self.shared_key, self.limit, deadline)
            if lease is None:
                raise self._busy("pool_full")
            held.append(lease)
        except StoreUnavailable:
            LIMITERS.store_failed()
            METRICS.incr("concurrency_fallback_total", pool=self.shared_key)
            self._release(held)
            with self._local(tenant):
                yield
            return
        except BaseException:
            self._release(held)
            raise
        try:
            yield
        finally:
            self._release(held)


def _too_large(limit: int) -> AppError:
    return AppError(f"Request body exceeds the {limit} byte limit for this endpoint", code="payload_too_large",
                    status_code=413)


class BodyLimitMiddleware:
    """Rejects oversized request bodies before they are buffered (declared and streamed sizes)."""

    def __init__(self, app, *, default_limit: int, upload_limit: int, upload_path: str):
        self.app, self.default_limit = app, default_limit
        self.upload_limit, self.upload_path = upload_limit, upload_path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_upload = scope["method"] == "POST" and scope["path"].rstrip("/") == self.upload_path
        limit = self.upload_limit if is_upload else self.default_limit
        declared = next((v for k, v in scope["headers"] if k == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > limit:
            body = json.dumps({"error": {"code": "payload_too_large", "message": str(_too_large(limit))}}).encode()
            return await send_response(send, 413, body)
        seen, exceeded = 0, False

        async def counting_receive():
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:  # chunked or mis-declared bodies are cut off while streaming
                    exceeded = True
                    raise _too_large(limit)
            return message

        async def guarded_send(message):
            # Frameworks may wrap a failed body read in their own 400; the client must see the real cause.
            if not exceeded:
                return await send(message)
            if message["type"] == "http.response.start":
                body = json.dumps({"error": {"code": "payload_too_large", "message": str(_too_large(limit))}}).encode()
                await send_response(send, 413, body)

        await self.app(scope, counting_receive, guarded_send)


async def send_response(send, status: int, body: bytes):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
