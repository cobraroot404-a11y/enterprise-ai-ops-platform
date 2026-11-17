"""Outbox worker entrypoint: submits approved tickets to each tenant's ticketing system.

Run: python workers/run_worker.py   (uses the restricted eaop_worker database role)
"""
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.database.session import Database  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.workflows.worker import WorkerConfig, process_one  # noqa: E402

log = logging.getLogger("eaop.worker")
_FINAL_DB: list = []  # the worker's database, so the last unflushed metrics are written on exit


def main(poll_seconds: float = 1.0) -> None:
    configure_logging()
    db = Database(get_settings(), role="worker", pool_size=2, max_overflow=2)
    from app.connectors.ratelimit import LIMITERS

    LIMITERS.use_database(db)  # limits are shared with the API and any other worker through the database
    from app.observability.metrics import start_flusher

    start_flusher(db, get_settings().metrics_flush_seconds)  # durable metrics, summed with the API's
    config = WorkerConfig()
    _FINAL_DB.append(db)
    log.info("worker started")
    from app.connectors.ratelimit import maintenance

    next_maintenance = 0.0
    while True:
        if time.monotonic() >= next_maintenance:  # every five minutes: sweep idle limiter rows and expired leases
            next_maintenance = time.monotonic() + 300
            swept = maintenance(db)
            if swept.get("buckets_removed") or swept.get("leases_removed") or swept.get("error"):
                log.info("limiter maintenance", extra=swept)
        try:
            outcome = process_one(db, config)
        except Exception:  # noqa: BLE001 - keep the loop alive; the event lease makes work recoverable
            log.exception("worker iteration failed")
            outcome = None
            time.sleep(poll_seconds * 3)
        if outcome is None:
            time.sleep(poll_seconds)
        else:
            log.info("processed outbox event", extra={"outcome": outcome})


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        from app.observability import metrics

        metrics.stop_flusher(_FINAL_DB[0] if _FINAL_DB else None)
