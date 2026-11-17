"""Idempotent, versioned, tenant-scoped document ingestion.

`ingest` is the single-call path (seeding, tests, scripts): parse, embed, store. The same three steps are exposed separately (`parse`, `embed_segments`, `store_parsed`) so the
durable job pipeline (app.ingestion.jobs) can persist the parsed segments, retry the embedding, and perform the final write under a fenced claim without duplicating any logic."""
import hashlib
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.embeddings import Embedder
from app.ai.safety import looks_like_injection
from app.ai.tuning import get_tuning
from app.audit import service as audit
from app.core.errors import DependencyUnavailable, Invalid
from app.ingestion import sources
from app.ingestion.parsers import Parsed, Segment, parse, safe_filename
from app.models import Document, DocumentChunk, DocumentVersion
from app.retrieval.profiles import ensure_active_profile, require_compatible

DOCUMENT_KINDS = {"equipment_manual", "inspection_report", "incident_history", "equipment_register",
                  "maintenance_log", "other"}


@dataclass
class IngestResult:
    document_id: str
    version: int
    status: str  # created | new_version | duplicate
    chunk_count: int


def find_duplicate(session: Session, *, tenant_id, user_id, filename: str, content_hash: str,
                   correlation_id: str | None = None) -> IngestResult | None:
    """Identical content already stored for an ACTIVE document of this tenant (deleted content is not a duplicate of anything)."""
    existing = session.scalar(
        select(DocumentVersion).join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.tenant_id == tenant_id, DocumentVersion.content_hash == content_hash,
               Document.lifecycle_status == "active"))
    if existing is None:
        return None
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="document.duplicate_ignored",
                 entity_type="document", entity_id=existing.document_id,
                 details={"filename": filename}, correlation_id=correlation_id)
    return IngestResult(str(existing.document_id), existing.version, "duplicate", existing.chunk_count)


def ingest(session: Session, *, tenant_id, user_id, filename: str, data: bytes, kind: str,
           embedder: Embedder, field_map: dict[str, str] | None = None, id_field: str | None = None,
           correlation_id: str | None = None, extra_kinds: frozenset[str] | set[str] = frozenset()) -> IngestResult:
    if kind not in DOCUMENT_KINDS and kind not in extra_kinds:
        raise Invalid(f"Unknown document kind '{kind}'", code="invalid_kind")
    filename = safe_filename(filename)
    content_hash = hashlib.sha256(data).hexdigest()
    for attempt in (1, 2):
        found = find_duplicate(session, tenant_id=tenant_id, user_id=user_id, filename=filename,
                               content_hash=content_hash, correlation_id=correlation_id)
        if found:
            return found
        try:
            return _ingest_new(session, tenant_id=tenant_id, user_id=user_id, filename=filename, data=data,
                               kind=kind, embedder=embedder, field_map=field_map, id_field=id_field,
                               correlation_id=correlation_id, content_hash=content_hash)
        except IntegrityError:
            # A concurrent upload of the same content (or first profile) won the race: resolve to its result.
            session.rollback()
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def embed_segments(embedder: Embedder, kind: str, filename: str, segments: list[Segment]) -> list:
    """Vectors for the segments. Any failure of the embedding model is a transient 503 (nothing has been written when this runs)."""
    try:
        prefix = ""
        if get_tuning().index_prefix:  # E1: document context in the embedded text only; stored text and quotes are unchanged
            prefix = f"{kind} {filename.rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ')}: "
        return embedder.embed([prefix + s.text for s in segments])
    except Exception as exc:  # noqa: BLE001 - nothing has been committed: the upload can simply be retried
        raise DependencyUnavailable("The embedding model is unavailable; nothing was stored, retry shortly",
                                    code="embedding_unavailable") from exc


def _ingest_new(session: Session, *, tenant_id, user_id, filename: str, data: bytes, kind: str,
                embedder: Embedder, field_map, id_field, correlation_id, content_hash: str) -> IngestResult:
    parsed, media_type = parse(filename, data, field_map=field_map, id_field=id_field)
    require_compatible(session, tenant_id, embedder)  # refuses to mix embedding models before any work is done
    vectors = embed_segments(embedder, kind, filename, parsed.segments)
    return store_parsed(session, tenant_id=tenant_id, user_id=user_id, filename=filename, kind=kind, content_hash=content_hash,
                        size_bytes=len(data), media_type=media_type, parsed=parsed, vectors=vectors, embedder=embedder,
                        correlation_id=correlation_id)


def store_parsed(session: Session, *, tenant_id, user_id, filename: str, kind: str, content_hash: str, size_bytes: int,
                 media_type: str, parsed: Parsed, vectors: list, embedder: Embedder, correlation_id=None,
                 job_id=None, source_id=None) -> IngestResult:
    """The final write: document, version and chunks (and, in the job pipeline, the job completion) belong to ONE transaction chosen by the caller.

    The target document is locked FOR UPDATE and re-checked as active, so a write that races a deletion either finishes before the deletion (which then removes it) or finds
    the document gone (the deletion freed its name) and creates a NEW document; it can never add chunks to, or revive, a deleted document."""
    profile = ensure_active_profile(session, tenant_id, embedder)
    source_key = filename.lower()
    document = session.scalar(select(Document).where(Document.tenant_id == tenant_id, Document.source_key == source_key,
                                                     Document.lifecycle_status == "active").with_for_update())
    if document:
        document.current_version += 1
        document.kind = kind
        status = "new_version"
        session.execute(update(DocumentChunk).where(DocumentChunk.document_id == document.id)
                        .values(is_current=False))
    else:
        document = Document(tenant_id=tenant_id, source_key=source_key, filename=filename, kind=kind,
                            current_version=1, created_by=user_id)
        session.add(document)
        status = "created"
    session.flush()
    version = DocumentVersion(
        tenant_id=tenant_id, document_id=document.id, version=document.current_version,
        content_hash=content_hash, size_bytes=size_bytes, media_type=media_type,
        page_count=parsed.page_count, chunk_count=len(parsed.segments), embedding_backend=embedder.name,
        processing_job_id=job_id, source_id=source_id)
    session.add(version)
    session.flush()
    if source_id is not None:  # the retained original belongs to this version, in the same transaction
        sources.link(session, tenant_id=tenant_id, source_id=source_id, document_id=document.id, version=version.version)
    for index, (segment, vector) in enumerate(zip(parsed.segments, vectors, strict=True)):
        session.add(DocumentChunk(
            tenant_id=tenant_id, document_id=document.id, version_id=version.id, version=version.version,
            chunk_index=index, text=segment.text, page_number=segment.page_number,
            record_id=segment.record_id, suspicious=looks_like_injection(segment.text),
            is_current=True, generation=1, embedding=vector, embedding_profile_id=profile.id))
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action=f"document.{status}",
                 entity_type="document", entity_id=document.id,
                 details={"filename": filename, "version": version.version, "chunks": len(parsed.segments),
                          "sha256": content_hash, "embedding_backend": embedder.name},
                 correlation_id=correlation_id)
    session.flush()
    return IngestResult(str(document.id), version.version, status, len(parsed.segments))
