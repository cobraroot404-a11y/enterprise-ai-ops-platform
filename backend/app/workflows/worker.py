"""Transactional-outbox worker that submits approved tickets to the tenant's ticketing system.

Safety properties:
  * Claims events with FOR UPDATE SKIP LOCKED and a lease, so concurrent workers never double-process
    and a crashed worker's event is reclaimed after the lease expires.
  * Re-verifies a recorded approval in the database before every external call.
  * Sends a stable Idempotency-Key (the ticket's key) so a retry after a lost response cannot create a
    second external ticket.
  * Classifies failures: transient -> backoff + RETRY_PENDING, permanent -> FAILED (dead letter).
"""

import datetime as dt
import logging
import time
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.connectors.clients import TicketingClient
from app.connectors.egress import tenant_slug
from app.connectors.http import PERMANENT, ConnectorError, backoff_delay
from app.database.session import Database
from app.ingestion.lifecycle import CLEANUP_TOPIC, CleanupRefused, cleanup_document, mark_cleanup_failed
from app.models import Approval, Connector, Incident, OutboxEvent, Ticket
from app.observability.logging import log_event
from app.observability.metrics import METRICS
from app.workflows import state_machine as sm
from app.workflows.ticket_service import SUBMIT_TOPIC, external_release_blocker

log = logging.getLogger("eaop.worker")


@dataclass
class WorkerConfig:
    max_attempts: int = 5
    lease_seconds: int = 60
    backoff_base: float = 2.0
    backoff_cap: float = 300.0
    http_timeout: float = 5.0
    embedder: object | None = None  # the embedding backend for ingestion jobs; None = the process's configured backend


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _audit(session: Session, ticket: Ticket, action: str, details: dict) -> None:
    audit.record(
        session,
        tenant_id=ticket.tenant_id,
        actor_type="worker",
        action=action,
        entity_type="ticket",
        entity_id=ticket.id,
        details=details,
    )


def _claim(db: Database, config: WorkerConfig, topic: str = SUBMIT_TOPIC) -> tuple[int, object, object] | None:
    with db.session() as s:
        now = _now()
        event = s.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == topic,
                or_(
                    and_(OutboxEvent.status == "pending", OutboxEvent.available_at <= now),
                    and_(OutboxEvent.status == "processing", OutboxEvent.locked_until < now),
                ),
            )
            .order_by(OutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            return None
        event.status = "processing"
        event.locked_until = now + dt.timedelta(seconds=config.lease_seconds)
        s.commit()
        return event.id, event.aggregate_id, event.tenant_id


def _finish_event(event: OutboxEvent, status: str, error: str | None = None) -> None:
    if status == "dead":  # every dead letter is counted, whatever the topic
        METRICS.incr("dead_letters_total", tenant=str(event.tenant_id), source=event.topic)
    event.status = status
    event.last_error = error
    event.locked_until = None
    event.processed_at = _now()


def process_one(db: Database, config: WorkerConfig | None = None) -> str | None:
    """Process at most one due event. Returns an outcome string, or None if nothing was due."""
    config = config or WorkerConfig()
    claimed = _claim(db, config)
    if claimed is None:
        outcome = process_cleanup_one(db, config)  # nothing to submit: look for a document cleanup that is due
        return outcome if outcome is not None else process_ingestion_one(db, config)
    from app.observability import tracing

    event_id, ticket_id, tenant_id = claimed
    with db.session() as s:
        stored = s.get(OutboxEvent, event_id)
        trace_id = (stored.payload or {}).get("trace_id") if stored is not None else None
    valid = isinstance(trace_id, str) and len(trace_id) == 32
    token = tracing.set_current(trace_id if valid else tracing.trace_id_for(str(ticket_id)))
    try:
        with tracing.span("outbox.submission", tenant_id=str(tenant_id)) as attrs:
            outcome = _run_claimed(db, config, event_id, ticket_id, tenant_id)
            attrs["outcome"] = outcome
            return outcome
    finally:
        tracing.reset(token)


def _run_claimed(db: Database, config: WorkerConfig, event_id, ticket_id, tenant_id) -> str:
    started = time.perf_counter()
    log_event(log, "submission.claimed", event_id=event_id, ticket_id=str(ticket_id), tenant_id=str(tenant_id))
    try:
        outcome = _process_claimed(db, config, event_id, ticket_id, tenant_id)
    except Exception as exc:
        METRICS.incr("submission_outcomes_total", tenant=str(tenant_id), outcome="error")
        METRICS.incr("errors_total", tenant=str(tenant_id), source="worker", error=type(exc).__name__)
        log_event(
            log,
            "submission.error",
            level=logging.ERROR,
            event_id=event_id,
            ticket_id=str(ticket_id),
            tenant_id=str(tenant_id),
            error_class=type(exc).__name__,
        )
        raise
    elapsed = time.perf_counter() - started
    METRICS.incr("submission_outcomes_total", tenant=str(tenant_id), outcome=outcome)
    METRICS.observe("submission_seconds", elapsed, tenant=str(tenant_id))
    if outcome == "retry_scheduled":
        METRICS.incr("submission_retries_total", tenant=str(tenant_id))
    log_event(
        log,
        "submission.outcome",
        level=logging.INFO if outcome in ("submitted", "already_submitted") else logging.WARNING,
        event_id=event_id,
        ticket_id=str(ticket_id),
        tenant_id=str(tenant_id),
        outcome=outcome,
        duration_ms=round(elapsed * 1000, 1),
    )
    return outcome


def _process_claimed(db: Database, config: WorkerConfig, event_id, ticket_id, tenant_id) -> str:

    # Phase 1: validate approval, mark SUBMITTING, snapshot what we need for the external call.
    with db.session() as s:
        event = s.get(OutboxEvent, event_id)
        ticket = s.scalar(select(Ticket).where(Ticket.id == ticket_id).with_for_update())
        if ticket is None:  # poison message: never retry forever, never block the queue
            _finish_event(event, "dead", "orphaned event: ticket does not exist")
            s.commit()
            return "orphaned"
        if ticket.state == sm.SUBMITTED:
            _finish_event(event, "done")
            s.commit()
            return "already_submitted"
        approval = s.scalar(select(Approval).where(Approval.ticket_id == ticket.id))
        if ticket.state not in sm.SUBMITTABLE or approval is None or approval.decision != "approved":
            _finish_event(event, "dead", "blocked: ticket is not approved")
            _audit(s, ticket, "submission.blocked", {"state": ticket.state})
            s.commit()
            return "blocked"
        blocker = external_release_blocker(s.get(Incident, ticket.incident_id))
        if blocker:  # defence in depth: the incident may have changed since approval
            _finish_event(event, "dead", f"blocked: {blocker[0]}")
            _audit(s, ticket, "submission.blocked", {"reason": blocker[0]})
            if ticket.state in (sm.SUBMITTING, sm.RETRY_PENDING):
                sm.transition(s, ticket, sm.FAILED, actor_type="worker", reason=blocker[1])
            ticket.last_error = blocker[1][:500]
            s.commit()
            return "blocked"
        connector = s.scalar(
            select(Connector).where(Connector.tenant_id == ticket.tenant_id, Connector.kind == "ticketing")
        )
        if connector is None:
            _finish_event(event, "dead", "no ticketing connector configured")
            if ticket.state != sm.SUBMITTING:
                sm.transition(s, ticket, sm.SUBMITTING, actor_type="worker")
            sm.transition(s, ticket, sm.FAILED, actor_type="worker", reason="no ticketing connector")
            ticket.last_error = "no ticketing connector configured"
            s.commit()
            return "failed_permanent"
        if ticket.state != sm.SUBMITTING:
            sm.transition(s, ticket, sm.SUBMITTING, actor_type="worker")
        ticket.attempts += 1
        incident = s.get(Incident, ticket.incident_id)
        payload = {
            "title": ticket.title,
            "description": ticket.description,
            "priority": ticket.priority,
            "asset_id": incident.asset_id if incident else None,
            "source_ticket_id": str(ticket.id),
        }
        key = str(ticket.idempotency_key)
        attempt = ticket.attempts
        client = TicketingClient.from_row(
            connector, tenant_slug=tenant_slug(s, ticket.tenant_id), timeout=config.http_timeout
        )
        s.commit()

    # Phase 2: external call, outside any DB transaction.
    external_id, error = None, None
    try:
        external_id = client.create_ticket(payload, key)
    except ConnectorError as exc:
        error = exc

    # Phase 3: record the outcome.
    with db.session() as s:
        event = s.get(OutboxEvent, event_id)
        ticket = s.scalar(select(Ticket).where(Ticket.id == ticket_id).with_for_update())
        event.attempts = attempt
        if error is None:
            ticket.external_ticket_id = external_id
            ticket.submitted_at = _now()
            METRICS.observe("workflow_completion_seconds", max(0.0, (ticket.submitted_at - ticket.created_at).total_seconds()), tenant=str(ticket.tenant_id))
            ticket.last_error = None
            sm.transition(s, ticket, sm.SUBMITTED, actor_type="worker")
            _audit(s, ticket, "ticket.submitted", {"external_ticket_id": external_id, "attempt": attempt})
            _finish_event(event, "done")
            s.commit()
            return "submitted"
        ticket.last_error = f"{error.kind}: {error}"[:500]
        permanent = error.kind == PERMANENT or attempt >= config.max_attempts
        if permanent:
            sm.transition(s, ticket, sm.FAILED, actor_type="worker", reason=ticket.last_error)
            _audit(s, ticket, "submission.dead_lettered", {"error": ticket.last_error, "attempt": attempt})
            _finish_event(event, "dead", ticket.last_error)
            s.commit()
            return "failed_permanent"
        sm.transition(s, ticket, sm.RETRY_PENDING, actor_type="worker", reason=ticket.last_error)
        delay = backoff_delay(attempt, config.backoff_base, config.backoff_cap)
        event.status = "pending"
        event.locked_until = None
        event.available_at = _now() + dt.timedelta(seconds=delay)
        event.last_error = ticket.last_error
        _audit(
            s,
            ticket,
            "submission.retry_scheduled",
            {"error": ticket.last_error, "attempt": attempt, "delay_seconds": round(delay, 2)},
        )
        s.commit()
        return "retry_scheduled"


def drain(db: Database, config: WorkerConfig | None = None, max_iterations: int = 100) -> list[str]:
    """Process due events until none remain (used by tests and the demo)."""
    outcomes = []
    for _ in range(max_iterations):
        outcome = process_one(db, config)
        if outcome is None:
            break
        outcomes.append(outcome)
    return outcomes


def process_cleanup_one(db: Database, config: WorkerConfig | None = None) -> str | None:
    """Stage B of document deletion for at most one due `document.cleanup` event.

    Every database action for the document runs in a session whose tenant context is the
    EVENT's tenant, so row-level security hides every other tenant's artifacts from the
    worker. Outcomes: cleanup_completed, cleanup_retry_scheduled, cleanup_failed, or
    cleanup_refused (a forged or orphaned event: marked dead, nothing deleted).
    """
    config = config or WorkerConfig()
    claimed = _claim(db, config, CLEANUP_TOPIC)
    if claimed is None:
        return None
    event_id, document_id, tenant_id = claimed
    try:
        with db.session(tenant_id=tenant_id) as s:
            result = cleanup_document(s, tenant_id=tenant_id, document_id=document_id)
            s.commit()
    except CleanupRefused as exc:
        with db.session() as s:
            event = s.get(OutboxEvent, event_id)
            event.attempts += 1
            _finish_event(event, "dead", f"refused: {exc}")
            s.commit()
        METRICS.incr("document_cleanup_total", tenant=str(tenant_id), outcome="refused")
        return "cleanup_refused"
    except Exception as exc:  # noqa: BLE001 - everything rolled back; retry with backoff, then record the failure
        error_class = type(exc).__name__
        outcome = "cleanup_retry_scheduled"
        with db.session() as s:
            event = s.get(OutboxEvent, event_id)
            event.attempts += 1
            if event.attempts >= config.max_attempts:
                _finish_event(event, "dead", error_class)
                outcome = "cleanup_failed"
            else:
                event.status, event.locked_until, event.last_error = "pending", None, error_class
                delay = backoff_delay(event.attempts, config.backoff_base, config.backoff_cap)
                event.available_at = _now() + dt.timedelta(seconds=delay)
            s.commit()
        if outcome == "cleanup_failed":
            with db.session(tenant_id=tenant_id) as s:
                mark_cleanup_failed(s, tenant_id=tenant_id, document_id=document_id, error_class=error_class)
                s.commit()
        METRICS.incr("document_cleanup_total", tenant=str(tenant_id), outcome=outcome)
        log_event(log, "document.cleanup." + outcome, level=logging.WARNING, event_id=event_id,
                  document_id=str(document_id), tenant_id=str(tenant_id), error_class=error_class)
        return outcome
    with db.session() as s:
        event = s.get(OutboxEvent, event_id)
        event.attempts += 1
        _finish_event(event, "done")
        s.commit()
    METRICS.incr("document_cleanup_total", tenant=str(tenant_id), outcome="completed")
    counts = {k: v for k, v in result.items() if k != "outcome"}
    log_event(log, "document.cleanup.completed", event_id=event_id, document_id=str(document_id),
              tenant_id=str(tenant_id), **counts)
    return "cleanup_completed"


def process_ingestion_one(db: Database, config: WorkerConfig | None = None) -> str | None:
    """Run at most one due ingestion job (a new upload's retry or a reprocessing request).

    Outcomes: ingestion_completed, ingestion_retry_scheduled, ingestion_failed, ingestion_cancelled (its document was
    deleted), ingestion_stale (the claim was lost to a newer one).
    """
    from app.ai.embeddings import get_embedder
    from app.core.config import get_settings
    from app.ingestion import jobs

    config = config or WorkerConfig()
    claimed = jobs.claim_next(db, config.lease_seconds)
    if claimed is None:
        return None
    embedder = config.embedder or get_embedder(get_settings().embedding_backend)
    outcome = jobs.execute(db, claimed, embedder, config.backoff_base, config.backoff_cap)
    log_event(log, f"ingestion.{outcome}", job_id=str(claimed.id), tenant_id=str(claimed.tenant_id),
              job_type=claimed.job_type)
    return f"ingestion_{outcome}"
