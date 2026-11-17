"""Tenant-aware operational metrics: fast in-process counters and timers, flushed into durable PostgreSQL series.

How it works:
  * Every process (API, worker) records into its own in-memory registry, which is cheap and lock-protected.
  * `flush(db)` writes the DELTA since the last successful flush into the additive `metric_series` table (migration 0015) through `metric_add`. Deltas from all processes sum, restarts lose
    nothing that was flushed, and a failed flush keeps its deltas for the next attempt (nothing is dropped, nothing double counted). A background thread flushes every few seconds; the
    worker flushes in its loop and at exit; the metrics endpoints flush the serving process before reading. A crash loses at most the unflushed interval of that process.
  * Timers are fixed-bucket histograms (BUCKETS) with a sum and a count, so percentiles are approximate on the durable side (the in-process snapshot still has exact recent samples).
  * Labels carry the tenant id (a UUID) and technical dimensions only: never document text, user input, credentials or tokens.
  * These are measurements of whatever ran locally (tests, demos, development), not production telemetry.
"""

import bisect
import hashlib
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

log = logging.getLogger("eaop.metrics")

MAX_SAMPLES = 2000
STARTED_AT = time.time()
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)  # upper bounds in seconds; one more implicit bucket for everything above
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _key(labels: dict) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in labels.items() if v is not None))


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    pos = (len(sorted_values) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def series_key(name: str, labels: dict) -> str:
    return hashlib.sha256((name + "|" + json.dumps(sorted(labels.items()))).encode()).hexdigest()


def bucket_label(index: int) -> str:
    return "+Inf" if index >= len(BUCKETS) else repr(BUCKETS[index])


class Registry:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple], int] = defaultdict(int)
        self._timers: dict[tuple[str, tuple], deque] = defaultdict(lambda: deque(maxlen=MAX_SAMPLES))
        self._totals: dict[tuple[str, tuple], list] = defaultdict(lambda: [0, 0.0])  # count, sum (not capped)
        self._hist: dict[tuple[str, tuple], list[int]] = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
        self._flushed_counters: dict[tuple[str, tuple], int] = {}
        self._flushed_hist: dict[tuple[str, tuple], list[int]] = {}
        self._flushed_totals: dict[tuple[str, tuple], list] = {}
        self._flush_lock = threading.Lock()

    def incr(self, name: str, value: int = 1, **labels) -> None:
        with self._lock:
            self._counters[(name, _key(labels))] += value

    def observe(self, name: str, seconds: float, **labels) -> None:
        with self._lock:
            k = (name, _key(labels))
            self._timers[k].append(seconds)
            self._totals[k][0] += 1
            self._totals[k][1] += seconds
            self._hist[k][bisect.bisect_left(BUCKETS, seconds)] += 1

    @contextmanager
    def timer(self, name: str, **labels):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, time.perf_counter() - start, **labels)

    def snapshot(self, tenant: str | None = None) -> dict:
        """Counters and latency summaries; with `tenant`, only series labelled with that tenant id."""

        def keep(labels: tuple) -> bool:
            return tenant is None or dict(labels).get("tenant") == tenant

        with self._lock:
            counters = [
                {"name": n, "labels": dict(lb), "value": v} for (n, lb), v in sorted(self._counters.items()) if keep(lb)
            ]
            timers = []
            for (n, lb), samples in sorted(self._timers.items()):
                if not keep(lb):
                    continue
                values = sorted(samples)
                count, total = self._totals[(n, lb)]
                timers.append(
                    {
                        "name": n,
                        "labels": dict(lb),
                        "count": count,
                        "mean_s": round(total / count, 6) if count else 0.0,
                        "p50_s": round(_percentile(values, 0.5), 6),
                        "p95_s": round(_percentile(values, 0.95), 6),
                        "max_s": round(max(values), 6) if values else 0.0,
                        "window": len(values),
                    }
                )
        return {
            "process_started_at": STARTED_AT,
            "uptime_s": round(time.time() - STARTED_AT, 1),
            "counters": counters,
            "timers": timers,
        }

    # ------------------------------------------------------------------------------------------------------------------------ durable flush
    def _pending(self):
        """(items, commit) where items are (series_key, name, labels, scope_tenant, delta > 0) since the last successful flush, and commit() advances the flushed marks."""
        items, new_counters, new_hist, new_totals = [], {}, {}, {}
        with self._lock:
            for k, value in self._counters.items():
                delta = value - self._flushed_counters.get(k, 0)
                new_counters[k] = value
                if delta > 0:
                    items.append((k[0], dict(k[1]), float(delta)))
            for k, counts in self._hist.items():
                done = self._flushed_hist.get(k, [0] * len(counts))
                new_hist[k] = list(counts)
                for i, (now, before) in enumerate(zip(counts, done, strict=True)):
                    if now - before > 0:
                        items.append((f"{k[0]}_bucket", {**dict(k[1]), "le": bucket_label(i)}, float(now - before)))
                count, total = self._totals[k]
                before_count, before_sum = self._flushed_totals.get(k, [0, 0.0])
                new_totals[k] = [count, total]
                if count - before_count > 0:
                    items.append((f"{k[0]}_count", dict(k[1]), float(count - before_count)))
                    items.append((f"{k[0]}_sum", dict(k[1]), max(0.0, total - before_sum)))

        def commit():
            with self._lock:
                self._flushed_counters.update(new_counters)
                self._flushed_hist.update(new_hist)
                self._flushed_totals.update(new_totals)

        rows = [(series_key(n, lb), n, lb, lb.get("tenant") if _UUID.match(str(lb.get("tenant", ""))) else None, delta) for n, lb, delta in items]
        return rows, commit

    def flush(self, db) -> int:
        """Write pending deltas to the durable store in one transaction. Returns the number of series written, or -1 when the database could not be reached (deltas are kept)."""
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError

        with self._flush_lock:  # one flush at a time per process, so the same delta is never sent twice
            rows, commit = self._pending()
            if not rows:
                return 0
            try:
                with db.session() as s:
                    for key, name, labels, scope, delta in rows:
                        s.execute(text("SELECT metric_add(:k, :n, CAST(:l AS jsonb), :s, :d)"), {"k": key, "n": name, "l": json.dumps(labels), "s": scope, "d": delta})
                    s.commit()
            except SQLAlchemyError as exc:
                log.warning("metrics flush failed (%s); deltas are kept for the next attempt", type(exc).__name__)
                return -1
            commit()
            return len(rows)

    def reset(self) -> None:
        with self._lock:
            for store in (self._counters, self._timers, self._totals, self._hist, self._flushed_counters, self._flushed_hist, self._flushed_totals):
                store.clear()


METRICS = Registry()

_flusher: dict = {"thread": None, "db": None, "stop": None}


def start_flusher(db, interval: float = 10.0) -> None:
    """Flush `METRICS` to `db` every `interval` seconds on a daemon thread. Idempotent: a second call only points the existing thread at the new database."""
    _flusher["db"] = db
    thread = _flusher["thread"]
    if thread is not None and thread.is_alive():
        return
    stop = threading.Event()

    def loop():
        while not stop.wait(interval):
            current = _flusher["db"]
            if current is not None:
                METRICS.flush(current)

    _flusher["stop"] = stop
    _flusher["thread"] = threading.Thread(target=loop, name="metrics-flusher", daemon=True)
    _flusher["thread"].start()


def stop_flusher(final_db=None) -> None:
    stop, thread = _flusher["stop"], _flusher["thread"]
    if stop is not None:
        stop.set()
    if thread is not None:
        thread.join(timeout=2.0)
    _flusher.update(thread=None, stop=None)
    if final_db is not None:
        METRICS.flush(final_db)


# ------------------------------------------------------------------------------------------------------------------------------ reading
def read_durable(session, tenant: str | None, *, everything: bool = False) -> list[dict]:
    """Durable series visible to a tenant (its own plus platform-level ones), or every series when `everything` (decided by the caller from the caller's role)."""
    from sqlalchemy import text

    rows = session.execute(text("SELECT name, labels, scope_tenant, value, updated_at FROM metric_read(:s, :a)"), {"s": tenant, "a": everything}).all()
    return [{"name": r[0], "labels": r[1], "scope_tenant": r[2], "value": r[3], "updated_at": r[4]} for r in rows]


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _label_text(labels: dict) -> str:
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items())) + "}" if labels else ""


def render_prometheus(series: list[dict]) -> str:
    """Prometheus text exposition (version 0.0.4). Histogram buckets are stored per bucket and made cumulative here."""
    out, buckets, plain = [], defaultdict(dict), []
    for item in series:
        name, labels, value = item["name"], dict(item["labels"]), item["value"]
        if name.endswith("_bucket") and "le" in labels:
            le = labels.pop("le")
            buckets[(name[: -len("_bucket")], tuple(sorted(labels.items())))][le] = value
        else:
            plain.append((name, labels, value))
    histogram_bases = {base for base, _ in buckets}
    typed = set()
    for name, labels, value in sorted(plain, key=lambda p: (p[0], sorted(p[1].items()))):
        base = re.sub(r"_(sum|count)$", "", name)
        if base in histogram_bases and name != base:
            continue  # emitted with its histogram below
        if name not in typed:
            typed.add(name)
            out.append(f"# TYPE eaop_{name} counter")
        out.append(f"eaop_{name}{_label_text(labels)} {value:g}")
    sums = {(re.sub(r"_sum$", "", n), tuple(sorted(lb.items()))): v for n, lb, v in plain if n.endswith("_sum")}
    counts = {(re.sub(r"_count$", "", n), tuple(sorted(lb.items()))): v for n, lb, v in plain if n.endswith("_count")}
    for base in sorted(histogram_bases):
        out.append(f"# TYPE eaop_{base} histogram")
        for (b, lab), by_le in sorted((item for item in buckets.items() if item[0][0] == base), key=lambda i: i[0][1]):
            labels, running = dict(lab), 0.0
            for i in range(len(BUCKETS) + 1):
                running += by_le.get(bucket_label(i), 0.0)
                out.append(f"eaop_{base}_bucket{_label_text({**labels, 'le': bucket_label(i)})} {running:g}")
            out.append(f"eaop_{base}_sum{_label_text(labels)} {sums.get((b, lab), 0.0):.6f}")
            out.append(f"eaop_{base}_count{_label_text(labels)} {counts.get((b, lab), running):g}")
    return "\n".join(out) + "\n"
