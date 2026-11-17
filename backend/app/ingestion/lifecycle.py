"""Document lifecycle (V41-12.05): immediate logical deletion, then reliable, idempotent, tenant-scoped content cleanup.

Stage A (`delete_document`, in the request transaction): the document is marked deleted by the SERVER (never by a client field), its chunks stop being current, the
name it held is freed, one outbox event `document.cleanup` is written and one audit event is recorded; all of it commits or none of it does. From that commit on, every
retrieval path, listing and direct fetch excludes the document (they filter `documents.lifecycle_status = 'active'`, and the chunks are no longer `is_current`).

Stage B (`cleanup_document`, run by the outbox worker inside a tenant-scoped session): remove the chunks (text and embeddings) and versions of the deleted document, redact
the quotes and summaries that were copied from those chunks into incident records, verify nothing is left, and only then mark the cleanup completed. One transaction: a failure
anywhere rolls everything back and the event is retried; running it again after success changes nothing.

What is kept, deliberately: the document row as a tombstone (id, tenant, filename, kind, who and when, cleanup state), the audit events (no text, no excerpts), the incidents,
tickets and approvals themselves (workflow history is never erased; only the document text copied into their citations and related-incident summaries is redacted).
Not covered: a legal-retention or regulatory-erasure policy (no such requirement was approved), backups taken before deletion, and text a person copied elsewhere by hand,
including ticket text already sent to an external system."""
import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, object_session

from app.audit import service as audit
from app.core.errors import NotFound
from app.ingestion import jobs, sources, sync
from app.models import Document, DocumentChunk, DocumentVersion, Incident, OutboxEvent

CLEANUP_TOPIC = "document.cleanup"
REDACTED = "[removed: the source document was deleted]"
ACTIVE = "active"
DELETED = "deleted"


class CleanupRefused(Exception):
    """The cleanup was asked to remove content that is not (or no longer) eligible: wrong tenant, unknown document, or a document that is not deleted."""


@dataclass
class DeletionState:
    id: str
    filename: str
    lifecycle_status: str
    cleanup_state: str
    deleted_at: str
    cleanup_completed_at: str | None
    already_deleted: bool

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _state(doc: Document, already: bool) -> DeletionState:
    return DeletionState(id=str(doc.id), filename=doc.filename, lifecycle_status=doc.lifecycle_status, cleanup_state=doc.cleanup_state,
                         deleted_at=doc.deleted_at.isoformat(), cleanup_completed_at=doc.cleanup_completed_at.isoformat() if doc.cleanup_completed_at else None, already_deleted=already)


def _enqueue(session: Session, doc: Document) -> None:
    session.add(OutboxEvent(tenant_id=doc.tenant_id, topic=CLEANUP_TOPIC, aggregate_id=doc.id, payload={}))


def delete_document(session: Session, *, tenant_id, user_id, document_id, correlation_id: str | None = None) -> DeletionState:
    """Stage A. Not found (unknown id, or another tenant's) raises NotFound. Repeating the request is safe: an already deleted document returns its current state without a
    new audit event, except that a cleanup which previously FAILED is queued again (the retry path)."""
    doc = session.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id).with_for_update())
    if doc is None:
        raise NotFound("Document not found")
    if doc.lifecycle_status == DELETED:
        if doc.cleanup_state == "failed":
            doc.cleanup_state = "pending"
            _enqueue(session, doc)
            audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="document.cleanup_requeued", entity_type="document", entity_id=doc.id,
                         details={"outcome": "requeued", "cleanup_state": "pending"}, correlation_id=correlation_id)
            session.flush()
        return _state(doc, already=True)
    chunks = session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.tenant_id == tenant_id))
    versions = session.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.tenant_id == tenant_id))
    doc.lifecycle_status = DELETED
    doc.deleted_at = _now()
    doc.deleted_by = user_id
    doc.cleanup_state = "pending"
    doc.source_key = f"deleted:{doc.id}"  # frees the file name: a later upload of the same name is a NEW document and can never revive this one
    session.execute(update(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.tenant_id == tenant_id).values(is_current=False))
    # The content hash identifies the deleted content and is unique per tenant: replace it at once, so the same bytes can be uploaded again as a NEW document straight away.
    session.execute(update(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.tenant_id == tenant_id)
                    .values(content_hash=func.concat("deleted:", DocumentVersion.id)))
    sync.mark_documents_deleted(session, tenant_id=tenant_id, document_id=doc.id)  # a connector will not resurrect it from an unchanged source record
    cancelled = jobs.cancel_for_document(session, tenant_id=tenant_id, document_id=doc.id, actor_id=user_id, correlation_id=correlation_id)
    _enqueue(session, doc)
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="document.deleted", entity_type="document", entity_id=doc.id,
                 details={"outcome": "logically_deleted", "cleanup_state": "pending", "versions": versions, "chunks": chunks, "jobs_cancelled": cancelled}, correlation_id=correlation_id)
    session.flush()
    return _state(doc, already=False)


def _redact(items: list, ids: set[str], field: str) -> tuple[list, int]:
    out, changed = [], 0
    for item in items or []:
        if isinstance(item, dict) and item.get("chunk_id") in ids and item.get(field) != REDACTED:
            item = {**item, field: REDACTED}
            changed += 1
        out.append(item)
    return out, changed


def _incidents_citing(session: Session, tenant_id, ids: list[str]) -> list[Incident]:
    rows = session.execute(text(
        "SELECT i.id FROM incidents i WHERE i.tenant_id = :t AND ("
        " EXISTS (SELECT 1 FROM jsonb_array_elements(i.citations) c WHERE c ->> 'chunk_id' = ANY(CAST(:ids AS text[])))"
        " OR EXISTS (SELECT 1 FROM jsonb_array_elements(i.related_incidents) r WHERE r ->> 'chunk_id' = ANY(CAST(:ids AS text[]))))"),
        {"t": str(tenant_id), "ids": ids}).all()
    return [session.get(Incident, r[0]) for r in rows]


def cleanup_document(session: Session, *, tenant_id, document_id, correlation_id: str | None = None) -> dict:
    """Stage B for one document inside an already tenant-scoped session (the caller commits). Idempotent: a completed cleanup returns immediately."""
    doc = session.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id).with_for_update())
    if doc is None:
        raise CleanupRefused("document not found in this tenant")
    if doc.lifecycle_status != DELETED:
        raise CleanupRefused("the document is not deleted: its content is never removed by the cleanup")
    if doc.cleanup_state == "completed":
        return {"outcome": "already_completed", "chunks_removed": 0, "versions_removed": 0, "incidents_redacted": 0}
    ids = [str(r[0]) for r in session.execute(select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id, DocumentChunk.tenant_id == tenant_id))]
    redacted = 0
    if ids:
        id_set = set(ids)
        for incident in _incidents_citing(session, tenant_id, ids):
            citations, a = _redact(incident.citations, id_set, "quote")
            related, b = _redact(incident.related_incidents, id_set, "summary")
            if a or b:
                incident.citations, incident.related_incidents = citations, related
                redacted += 1
    chunks = session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id, DocumentChunk.tenant_id == tenant_id)).rowcount
    originals = sources.purge_document(session, tenant_id=tenant_id, document_id=doc.id)  # the retained original files of every version
    versions = session.execute(delete(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.tenant_id == tenant_id)).rowcount
    session.flush()
    left = session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id)) \
        + session.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == doc.id)) \
        + sources.remaining(session, tenant_id=tenant_id, document_id=doc.id)
    if left:  # the verification gate: never report completion while content remains
        raise RuntimeError(f"cleanup verification failed: {left} artifacts remain")
    doc.cleanup_state = "completed"
    doc.cleanup_completed_at = _now()
    audit.record(session, tenant_id=tenant_id, actor_type="worker", action="document.cleanup_completed", entity_type="document", entity_id=doc.id,
                 details={"outcome": "content_removed", "cleanup_state": "completed", "chunks_removed": chunks, "versions_removed": versions, "sources_removed": originals, "incidents_redacted": redacted},
                 correlation_id=correlation_id)
    session.flush()
    return {"outcome": "completed", "chunks_removed": chunks, "versions_removed": versions, "sources_removed": originals, "incidents_redacted": redacted}


def mark_cleanup_failed(session: Session, *, tenant_id, document_id, error_class: str) -> None:
    """After the retry budget is spent: record the failure (state and audit; no text) so a later repeat of the delete request can queue it again."""
    doc = session.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id).with_for_update())
    if doc is None or doc.lifecycle_status != DELETED or doc.cleanup_state == "completed":
        return
    doc.cleanup_state = "failed"
    audit.record(session, tenant_id=tenant_id, actor_type="worker", action="document.cleanup_failed", entity_type="document", entity_id=doc.id,
                 details={"outcome": "cleanup_failed", "cleanup_state": "failed", "error_class": error_class})
    session.flush()


def mask_deleted_sources(incident: Incident, out: dict) -> dict:
    """Read-time guard for the window between logical deletion and cleanup: citations and related-incident summaries whose chunk belongs to a deleted document are returned
    redacted, exactly as the cleanup will persist them. Uses the incident's own (tenant-scoped) session; chunk ids that do not exist are left alone."""
    session = object_session(incident)
    ids = [c.get("chunk_id") for c in (out.get("citations") or [])] + [r.get("chunk_id") for r in (out.get("related_incidents") or [])]
    ids = sorted({i for i in ids if i})
    if session is None or not ids:
        return out
    gone = {str(r[0]) for r in session.execute(text(
        "SELECT c.id FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.tenant_id = :t AND d.tenant_id = :t AND d.lifecycle_status = 'deleted' AND c.id = ANY(CAST(:ids AS uuid[]))"), {"t": str(incident.tenant_id), "ids": ids})}
    if not gone:
        return out
    out["citations"], _ = _redact(out["citations"], gone, "quote")
    out["related_incidents"], _ = _redact(out["related_incidents"], gone, "summary")
    return out
