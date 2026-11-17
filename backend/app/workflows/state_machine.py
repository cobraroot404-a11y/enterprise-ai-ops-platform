"""Ticket state machine. Every status change goes through transition(); nothing else writes state."""
import datetime as dt
import logging

from app.audit import service as audit
from app.core.errors import Conflict
from app.observability.logging import log_event
from app.observability.metrics import METRICS

log = logging.getLogger("eaop.workflow")

DRAFT, PENDING, APPROVED, REJECTED = "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED"
SUBMITTING, SUBMITTED, FAILED, RETRY_PENDING, CANCELLED = (
    "SUBMITTING", "SUBMITTED", "FAILED", "RETRY_PENDING", "CANCELLED")

TRANSITIONS: dict[str, set[str]] = {
    DRAFT: {PENDING, CANCELLED},
    PENDING: {APPROVED, REJECTED, CANCELLED},
    APPROVED: {SUBMITTING, CANCELLED},
    SUBMITTING: {SUBMITTED, FAILED, RETRY_PENDING},
    RETRY_PENDING: {SUBMITTING, FAILED},
    FAILED: {RETRY_PENDING},
    REJECTED: set(),
    SUBMITTED: set(),
    CANCELLED: set(),
}
# States from which the worker may call the external system. Approval is also re-verified from the
# approvals table, so a state value alone can never authorize submission.
SUBMITTABLE = {APPROVED, RETRY_PENDING, SUBMITTING}


class InvalidTransition(Conflict):
    code = "invalid_transition"


def transition(session, ticket, new_state: str, *, actor_id=None, actor_type: str = "user",
               reason: str | None = None, correlation_id: str | None = None) -> None:
    if new_state not in TRANSITIONS.get(ticket.state, set()):
        raise InvalidTransition(f"Ticket cannot move from {ticket.state} to {new_state}")
    previous = ticket.state
    METRICS.incr("ticket_transitions_total", tenant=str(ticket.tenant_id), from_state=previous, to_state=new_state)
    log_event(log, "ticket.transition", tenant_id=str(ticket.tenant_id), ticket_id=str(ticket.id), from_state=previous,
              to_state=new_state, actor_type=actor_type, correlation_id=correlation_id)
    ticket.state = new_state
    ticket.updated_at = dt.datetime.now(dt.timezone.utc)
    audit.record(session, tenant_id=ticket.tenant_id, actor_id=actor_id, actor_type=actor_type,
                 action="ticket.transition", entity_type="ticket", entity_id=ticket.id,
                 details={"from": previous, "to": new_state, "reason": reason}, correlation_id=correlation_id)
