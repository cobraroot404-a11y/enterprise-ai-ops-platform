"""Token-bucket rate limiting: shared across processes through PostgreSQL, with a process-local fallback.

One bucket per (tenant, connector). When the registry has a database (`LIMITERS.use_database`, done by the API at start-up and by the worker for each job) buckets live in the
`rate_limit_state` table behind SECURITY DEFINER functions (migration 0015): every API and worker process draws from the same bucket, refill uses the database clock, and each take locks
the one bucket row, so concurrent callers cannot over-spend. If the database cannot be reached, the call falls back to a process-local bucket (still limited, per process, never
unlimited) and the event is counted in `ratelimit_store_unavailable_total`; after a failure the shared store is not retried for a few seconds so a database outage does not slow every
call. Waiting is bounded (MAX_WAIT_SECONDS), never a busy loop, and a stop event makes a waiter return at once. Keys carry the tenant id, so one tenant's configuration or Retry-After
pause can never slow another tenant. Limits: the database is a single point for the shared view; very high rates (hundreds per second on one bucket) serialise on one row lock.
"""
import logging
import threading
import time

log = logging.getLogger("eaop.ratelimit")

MAX_WAIT_SECONDS = 30.0  # the longest a caller is ever made to wait for a token or an upstream Retry-After pause
STORE_RETRY_SECONDS = 5.0  # after a store failure, use local buckets for this long before trying the database again
STORE_LOCK_TIMEOUT_MS = 2000


class RateLimited(Exception):
    """The bounded wait ended before a request could be allowed (the caller treats it as a transient failure and retries later)."""

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after  # seconds until a token should be available, when known


class StoreUnavailable(Exception):
    """The shared (database) store could not be used for this call."""


class TokenBucket:
    """Process-local bucket (also the fallback when the shared store is unavailable)."""

    def __init__(self, rate: float, burst: int, clock=time.monotonic):
        if not (0 < rate <= 1000) or not (1 <= burst <= 1000):
            raise ValueError("invalid rate limit")
        self.rate, self.capacity, self._clock = float(rate), float(burst), clock
        self._tokens, self._stamp, self._paused_until = float(burst), clock(), 0.0
        self._cond = threading.Condition()

    def _refill(self, now: float) -> None:
        self._tokens = min(self.capacity, self._tokens + (now - self._stamp) * self.rate)
        self._stamp = now

    def pause(self, seconds: float) -> None:
        """Honour an upstream Retry-After: no token is granted until it has passed (bounded by MAX_WAIT_SECONDS)."""
        with self._cond:
            self._paused_until = max(self._paused_until, self._clock() + min(max(seconds, 0.0), MAX_WAIT_SECONDS))

    def acquire(self, max_wait: float = MAX_WAIT_SECONDS, stop: threading.Event | None = None) -> float:
        """Take one token, waiting at most `max_wait` seconds. Returns the seconds waited; raises RateLimited when the bound is reached or `stop` is set."""
        max_wait = min(max_wait, MAX_WAIT_SECONDS)
        start = self._clock()
        deadline = start + max_wait
        with self._cond:
            while True:
                if stop is not None and stop.is_set():
                    raise RateLimited("stopped")
                now = self._clock()
                if now >= self._paused_until:
                    self._refill(now)
                    if self._tokens >= 1.0:
                        self._tokens -= 1.0
                        return now - start
                    need = (1.0 - self._tokens) / self.rate
                else:
                    need = self._paused_until - now
                if now + need > deadline:
                    raise RateLimited("rate limit wait bound reached", retry_after=need)
                self._cond.wait(timeout=min(need, 0.25) if stop is not None else need)  # short slices only when a stop event must be noticed


class SharedStore:
    """Calls the SECURITY DEFINER functions of migration 0015, each in its own short transaction (the bucket row lock is held only for the call)."""

    def __init__(self, db):
        self.db = db

    def _call(self, sql: str, params: dict):
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        try:
            with self.db.session() as s:
                s.execute(text(f"SET LOCAL lock_timeout = '{STORE_LOCK_TIMEOUT_MS}ms'"))
                value = s.execute(text(sql), params).scalar()
                s.commit()
                return value
        except SQLAlchemyError as exc:
            raise StoreUnavailable(type(exc).__name__) from exc

    def take(self, key: str, rate: float, burst: int, cost: float = 1.0) -> float:
        return float(self._call("SELECT rate_limit_take(:k, :r, :b, :c)", {"k": key, "r": rate, "b": burst, "c": cost}))

    def pause(self, key: str, seconds: float) -> None:
        self._call("SELECT rate_limit_pause(:k, :s)", {"k": key, "s": float(seconds)})

    def window_wait(self, key: str, window: int, maximum: int) -> int:
        return int(self._call("SELECT rate_limit_window_wait(:k, :w, :m)", {"k": key, "w": window, "m": maximum}) or 0)

    def window_add(self, key: str, window: int) -> int:
        return int(self._call("SELECT rate_limit_window_add(:k, :w)", {"k": key, "w": window}) or 0)

    def window_clear(self, key: str) -> None:
        self._call("SELECT rate_limit_window_clear(:k)", {"k": key})

    def lease_acquire(self, key: str, limit: int, ttl_seconds: int):
        return self._call("SELECT concurrency_acquire(:k, :l, :t)", {"k": key, "l": limit, "t": ttl_seconds})

    def lease_release(self, lease) -> None:
        self._call("SELECT concurrency_release(:i)", {"i": str(lease)})

    def sweep(self, idle_seconds: int = 3600) -> int:
        return int(self._call("SELECT rate_limit_sweep(:i)", {"i": idle_seconds}) or 0)

    def lease_sweep(self) -> int:
        return int(self._call("SELECT concurrency_sweep()", {}) or 0)


class SharedBucket:
    """The same interface as TokenBucket (`acquire`, `pause`), backed by the shared store with a process-local fallback."""

    def __init__(self, registry: "RateLimiters", key: str, rate: float, burst: int):
        self.registry, self.key, self.rate, self.capacity = registry, key, float(rate), float(burst)
        self.local = TokenBucket(rate, burst)

    def pause(self, seconds: float) -> None:
        store = self.registry.usable_store()
        if store is not None:
            try:
                store.pause(self.key, seconds)
                return
            except StoreUnavailable:
                self.registry.store_failed()
        self.local.pause(seconds)

    def acquire(self, max_wait: float = MAX_WAIT_SECONDS, stop: threading.Event | None = None) -> float:
        max_wait = min(max_wait, MAX_WAIT_SECONDS)
        start = time.monotonic()
        deadline = start + max_wait
        while True:
            if stop is not None and stop.is_set():
                raise RateLimited("stopped")
            store = self.registry.usable_store()
            if store is None:
                return self.local.acquire(max(0.0, deadline - time.monotonic()), stop)
            try:
                wait = store.take(self.key, self.rate, int(self.capacity))
            except StoreUnavailable:
                self.registry.store_failed()
                continue  # the next iteration uses the local fallback
            if wait <= 0:
                return time.monotonic() - start
            if time.monotonic() + wait > deadline:
                raise RateLimited("rate limit wait bound reached", retry_after=wait)
            pause = min(wait, 0.25) if stop is not None else wait
            if stop is not None:
                stop.wait(pause)
            else:
                time.sleep(pause)


class RateLimiters:
    """Registry of buckets; a changed rate or burst replaces the bucket for that connector only."""

    def __init__(self):
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], object] = {}
        self._store: SharedStore | None = None
        self._down_until = 0.0

    @property
    def database(self):
        return self._store.db if self._store else None

    @property
    def store(self) -> SharedStore | None:
        return self._store

    def use_database(self, db) -> None:
        """Share limits through this database (None goes back to process-local buckets); existing buckets are rebuilt on next use."""
        with self._lock:
            self._store = SharedStore(db) if db is not None else None
            self._down_until = 0.0
            self._buckets.clear()

    def usable_store(self) -> SharedStore | None:
        return self._store if self._store is not None and time.monotonic() >= self._down_until else None

    def store_failed(self) -> None:
        from app.observability.metrics import METRICS

        METRICS.incr("ratelimit_store_unavailable_total")
        with self._lock:
            first = time.monotonic() >= self._down_until
            self._down_until = time.monotonic() + STORE_RETRY_SECONDS
        if first:
            log.warning("shared rate-limit store unavailable; using process-local buckets for %.0f s", STORE_RETRY_SECONDS)

    def get(self, tenant_id, connector_id, rate: float, burst: int):
        if not (0 < rate <= 1000) or not (1 <= burst <= 1000):
            raise ValueError("invalid rate limit")
        key = (str(tenant_id), str(connector_id))
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or bucket.rate != float(rate) or bucket.capacity != float(burst):
                bucket = self._buckets[key] = (SharedBucket(self, f"bucket:{key[0]}:{key[1]}", rate, burst) if self._store is not None else TokenBucket(rate, burst))
            return bucket

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()


LIMITERS = RateLimiters()


def maintenance(db, idle_seconds: int = 3600) -> dict:
    """Housekeeping for the shared limiter tables: remove idle rate-limit buckets and counters (so keys such as failed sign-in addresses cannot accumulate without bound) and expired
    concurrency leases. Safe to run from any process at any time; errors are reported, never raised (limits keep working without it)."""
    store = SharedStore(db)
    try:
        return {"buckets_removed": store.sweep(idle_seconds), "leases_removed": store.lease_sweep()}
    except StoreUnavailable as exc:
        return {"error": str(exc)}
