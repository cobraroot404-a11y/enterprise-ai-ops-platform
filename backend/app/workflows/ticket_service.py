"""Ticket lifecycle operations used by the API. All state changes lock the ticket row first."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.errors import Conflict, Forbidden, NotFound
from app.models import Approval, Incident, OutboxEvent, Ticket
from app.observability.metrics import METRICS
from app.workflows import state_machine as sm

SUBMIT_TOPIC = "ticket.submit"


def _locked(session: Session, tenant_id, ticket_id) -> Ticket:
    ticket = session.scalar(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
                            .with_for_update())
    if ticket is None:
        raise NotFound("Ticket not found")
    return ticket


def get_ticket(session: Session, tenant_id, ticket_id) -> Ticket:
    ticket = session.scalar(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
    if ticket is None:
        raise NotFound("Ticket not found")
    return ticket


def build_description(incident: Incident) -> str:
    lines = [
        f"Asset: {incident.asset_id}" + ("" if incident.asset_verified else " (not in equipment register)"),
        f"Category: {incident.category}",
        f"Symptoms: {', '.join(incident.symptoms)}",
        "", f"Recommended action: {incident.recommended_action}", "",
        "Evidence:",
    ]
    lines += [f"  [{c['marker']}] {c['filename']} v{c['version']}"
              + (f" p.{c['page_number']}" if c.get("page_number") else "")
              + (f" record {c['record_id']}" if c.get("record_id") else "") for c in incident.citations] or [
        "  (none)"]
    if incident.related_incidents:
        lines += ["", "Related incidents:"] + [
            f"  {r.get('record_id') or 'n/a'} ({r['filename']})" for r in incident.related_incidents]
    if incident.notes:
        lines += ["", "Notes:"] + [f"  {n}" for n in incident.notes]
    return "\n".join(lines)


def external_release_blocker(incident: Incident | None) -> tuple[str, str] | None:
    """Reason an incident may not leave the platform, as (error code, message); None if cleared.

    Human incident review and ticket approval are separate gates: a supervisor accepting an incident
    never marks an unregistered asset as verified, so the asset must be registered (equipment register
    ingestion) and re-verified before anything is sent to an external system.
    """
    if incident is None or incident.review_status not in ("pending_review", "accepted"):
        return "incident_not_cleared", "The incident has not cleared human review"
    if not incident.asset_verified:
        return ("asset_not_registered", f"Asset {incident.asset_id} is not in the tenant's authoritative register; "
                "register it and re-verify the incident before external submission")
    return None


def _assert_releasable(session: Session, ticket: Ticket) -> None:
    blocker = external_release_blocker(session.get(Incident, ticket.incident_id))
    if blocker:
        raise Conflict(blocker[1], code=blocker[0])


def create_draft(session: Session, *, tenant_id, user_id, incident_id, correlation_id=None) -> Ticket:
    incident = session.scalar(select(Incident).where(Incident.id == incident_id, Incident.tenant_id == tenant_id))
    if incident is None:
        raise NotFound("Incident not found")
    if incident.review_status not in ("pending_review", "accepted"):
        raise Conflict(f"Incident review status is '{incident.review_status}'; a supervisor must review and "
                       "accept it before a ticket can be drafted", code="incident_needs_review")
    ticket = Ticket(tenant_id=tenant_id, incident_id=incident.id, created_by=user_id,
                    title=f"[{incident.priority}] {incident.category.replace('_', ' ')} on {incident.asset_id}",
                    description=build_description(incident), priority=incident.priority)
    session.add(ticket)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("An active ticket already exists for this incident",
                       code="duplicate_ticket") from exc
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="ticket.drafted",
                 entity_type="ticket", entity_id=ticket.id, details={"incident_id": str(incident.id)},
                 correlation_id=correlation_id)
    return ticket


def update_draft(session: Session, *, tenant_id, user_id, ticket_id, changes: dict, correlation_id=None) -> Ticket:
    ticket = _locked(session, tenant_id, ticket_id)
    if ticket.state != sm.DRAFT:
        raise Conflict(f"Only DRAFT tickets can be edited (state is {ticket.state})", code="not_editable")
    for key, value in changes.items():
        setattr(ticket, key, value)
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="ticket.edited", entity_type="ticket",
                 entity_id=ticket.id, details={"fields": sorted(changes)}, correlation_id=correlation_id)
    return ticket


def request_approval(session: Session, *, tenant_id, user_id, ticket_id, correlation_id=None) -> Ticket:
    ticket = _locked(session, tenant_id, ticket_id)
    sm.transition(session, ticket, sm.PENDING, actor_id=user_id, correlation_id=correlation_id)
    return ticket


def cancel(session: Session, *, tenant_id, user_id, ticket_id, correlation_id=None) -> Ticket:
    ticket = _locked(session, tenant_id, ticket_id)
    sm.transition(session, ticket, sm.CANCELLED, actor_id=user_id, correlation_id=correlation_id)
    return ticket


def _trace_payload() -> dict:
    from app.observability.tracing import current

    return {"trace_id": current()} if current() else {}


def enqueue_submission(session: Session, ticket: Ticket) -> None:
    """Idempotent: the partial unique index allows at most one active submit event per ticket."""
    session.execute(pg_insert(OutboxEvent).values(
        tenant_id=ticket.tenant_id, topic=SUBMIT_TOPIC, aggregate_id=ticket.id, payload=_trace_payload(),
        status="pending",
    ).on_conflict_do_nothing())


def decide(session: Session, *, tenant_id, user_id, ticket_id, decision: str, comment: str | None,
           correlation_id=None) -> Ticket:
    ticket = _locked(session, tenant_id, ticket_id)  # row lock serializes concurrent decisions
    if ticket.state != sm.PENDING:
        raise Conflict(f"Ticket is {ticket.state}, not PENDING_APPROVAL", code="not_pending_approval")
    if ticket.created_by == user_id:
        raise Forbidden("Separation of duties: the ticket author cannot decide on their own ticket",
                        code="self_approval")
    if decision == "approved":
        _assert_releasable(session, ticket)  # nothing is recorded if the incident may not be released
    session.add(Approval(tenant_id=tenant_id, ticket_id=ticket.id, decision=decision, decided_by=user_id,
                         comment=comment, requested_at=ticket.updated_at))
    if ticket.updated_at is not None:  # approval turnaround: from the request for approval to the decision
        METRICS.observe("approval_turnaround_seconds", max(0.0, (dt.datetime.now(dt.timezone.utc) - ticket.updated_at).total_seconds()),
                        tenant=str(tenant_id), decision=decision)
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action=f"approval.{decision}",
                 entity_type="ticket", entity_id=ticket.id, details={"comment": comment},
                 correlation_id=correlation_id)
    if decision == "approved":
        _assert_releasable(session, ticket)
        sm.transition(session, ticket, sm.APPROVED, actor_id=user_id, correlation_id=correlation_id)
        enqueue_submission(session, ticket)
    else:
        sm.transition(session, ticket, sm.REJECTED, actor_id=user_id, reason=comment,
                      correlation_id=correlation_id)
    return ticket


def submit(session: Session, *, tenant_id, user_id, ticket_id, correlation_id=None) -> Ticket:
    """Direct submit request. Only an already-approved ticket can be queued; nothing else can."""
    ticket = _locked(session, tenant_id, ticket_id)
    approved = session.scalar(select(Approval).where(Approval.ticket_id == ticket.id,
                                                     Approval.decision == "approved"))
    if ticket.state != sm.APPROVED or approved is None:
        raise Conflict(f"Ticket is {ticket.state}; only APPROVED tickets can be submitted",
                       code="approval_required")
    _assert_releasable(session, ticket)
    enqueue_submission(session, ticket)
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="ticket.submit_requested",
                 entity_type="ticket", entity_id=ticket.id, correlation_id=correlation_id)
    return ticket


def retry(session: Session, *, tenant_id, user_id, ticket_id, correlation_id=None) -> Ticket:
    """Manual retry of a FAILED ticket. Requires the original recorded approval; never creates one."""
    ticket = _locked(session, tenant_id, ticket_id)
    approved = session.scalar(select(Approval).where(Approval.ticket_id == ticket.id,
                                                     Approval.decision == "approved"))
    if ticket.state != sm.FAILED or approved is None:
        raise Conflict(f"Ticket is {ticket.state}; only FAILED approved tickets can be retried",
                       code="not_retryable")
    _assert_releasable(session, ticket)
    ticket.attempts = 0
    ticket.last_error = None
    sm.transition(session, ticket, sm.RETRY_PENDING, actor_id=user_id, reason="manual retry",
                  correlation_id=correlation_id)
    enqueue_submission(session, ticket)
    return ticket
