"""Append-only audit trail."""
from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(session: Session, *, tenant_id, action: str, entity_type: str, entity_id=None, actor_id=None,
           actor_type: str = "user", details: dict | None = None, correlation_id: str | None = None) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id, actor_id=actor_id, actor_type=actor_type, action=action,
        entity_type=entity_type, entity_id=str(entity_id) if entity_id else None,
        details=details or {}, correlation_id=correlation_id,
    )
    session.add(event)
    return event
