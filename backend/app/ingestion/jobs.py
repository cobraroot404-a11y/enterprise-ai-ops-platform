"""Durable ingestion jobs: state machine, bounded retry, fenced claims, uploads with a persistent record, and safe reprocessing (V41-12.03, V41-12.04).

State machine (every change goes through `set_status`; callers and models can never set a state):
  QUEUED -> PROCESSING | CANCELLED          RETRY_PENDING -> PROCESSING | CANCELLED
  PROCESSING -> COMPLETED | RETRY_PENDING | FAILED | CANCELLED
  FAILED -> QUEUED (authorised manual retry of a reprocessing job only)       COMPLETED and CANCELLED are final.
Safety properties:
  * a claim is a lease with a fencing token; every later write (retry, failure, completion, final data write) re-locks the job row and refuses unless the token still matches and
    the job is still PROCESSING, so a stale worker can never overwrite newer state and a completed job is never completed twice;
  * a lease that expires (worker crash) is reclaimed; the lost attempt counts, so retries are bounded; transient failures back off exponentially; permanent failures fail at once;
  * the final write of content happens in the SAME transaction as the job completion, and re-locks the document row and re-checks that it is active, so a deleted document
    can never be revived by a late worker or retry; a deletion cancels the document's active jobs;
  * error details are fixed, sanitised messages (never document text, never an exception string).
Nothing here claims exactly-once execution: attempts can be repeated, the observable outcome (one set of active chunks, one document version per content, one job completion) is idempotent."""
import datetime as dt
import hashlib
import logging
import time
import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.ai.embeddings import Embedder
from app.ai.safety import _PATTERNS, looks_like_injection
from app.ai.tuning import get_tuning
from app.audit import service as audit
from app.connectors.http import backoff_delay
from app.core.errors import AppError, Conflict, DependencyUnavailable, Invalid, NotFound
from app.database.session import Database
from app.ingestion import sources
from app.ingestion.parsers import Parsed, Segment, parse, safe_filename
from app.ingestion.service import DOCUMENT_KINDS, IngestResult, embed_segments, find_duplicate, store_parsed
from app.models import Document, DocumentChunk, DocumentVersion, IngestionJob
from app.observability.logging import log_event
from app.observability.metrics import METRICS
from app.retrieval.profiles import ensure_active_profile, require_compatible

log = logging.getLogger("eaop.ingestion")

QUEUED, PROCESSING, RETRY_PENDING, COMPLETED, FAILED, CANCELLED = "QUEUED", "PROCESSING", "RETRY_PENDING", "COMPLETED", "FAILED", "CANCELLED"
ACTIVE = (QUEUED, PROCESSING, RETRY_PENDING)
TERMINAL = (COMPLETED, FAILED, CANCELLED)
TRANSITIONS: dict[str, set[str]] = {
    QUEUED: {PROCESSING, CANCELLED},
    RETRY_PENDING: {PROCESSING, CANCELLED},
    PROCESSING: {COMPLETED, RETRY_PENDING, FAILED, CANCELLED},
    FAILED: {QUEUED},
    COMPLETED: set(),
    CANCELLED: set(),
}
DEFAULT_MAX_ATTEMPTS = 5
LEASE_SECONDS = 60
INFLIGHT_WAIT_SECONDS = 15.0  # how long a duplicate upload waits for the request already processing the same content before answering 503 ingestion_in_progress
BACKOFF_BASE, BACKOFF_CAP = 2.0, 300.0

SAFE_DETAIL = {
    "embedding_unavailable": "The embedding model was unavailable",
    "database_unavailable": "The database was temporarily unavailable",
    "retries_exhausted": "The retry limit was reached",
    "document_deleted": "The document was deleted",
    "unexpected_error": "An unexpected error occurred while processing",
    "source_changed": "The document content changed while the job was waiting",
    "claim_lost": "The processing claim was lost",
    "credentials_missing": "The connector credentials are not configured",
    "source_unauthorized": "The source rejected the connector credentials",
    "source_unavailable": "The source was unavailable",
    "source_rate_limited": "The source rate limit was reached",
    "source_schema_invalid": "The source returned an unexpected response shape",
    "source_rejected": "The source rejected the request",
    "invalid_cursor": "The source returned an invalid continuation",
    "pagination_loop": "The source pagination did not advance",
    "missing_continuation": "The source promised more data but gave no continuation",
    "egress_denied": "The connector destination is not permitted",
    "source_record_invalid": "A source record failed validation",
    "worker_stopping": "The worker was stopping",
    "invalid_connector_config": "The connector configuration is invalid",
    "connector_not_found": "The connector no longer exists",
    "source_missing": "The retained original content is no longer available",
    "source_corrupted": "The retained original content failed its integrity check",
    "source_not_retained": "No original content is retained for this job",
}


class InvalidJobTransition(Conflict):
    code = "invalid_job_transition"


class StaleClaim(Exception):
    """The job is no longer claimed by this worker (cancelled, reclaimed or already finished): the caller writes nothing."""


class JobCancelled(Exception):
    """The document was deleted (or is gone): the job ends CANCELLED and nothing is written."""


class SourceChanged(Exception):
    """The document's active content changed since the job read it: the job fails permanently instead of overwriting newer content."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def processing_config(embedder: Embedder) -> dict:
    spec = embedder.profile
    heuristics = hashlib.sha256("|".join(_PATTERNS).encode()).hexdigest()[:10]
    return {"embedding_backend": embedder.name, "embedding_model": f"{spec.provider}:{spec.model}@{spec.revision}", "index_prefix": bool(get_tuning().index_prefix),
            "safety_heuristics": heuristics}


# ------------------------------------------------------------------------------------------------------------------------------------ state machine
def set_status(job: IngestionJob, new: str, *, error_code: str | None = None) -> None:
    if new not in TRANSITIONS[job.status]:
        raise InvalidJobTransition(f"Ingestion job cannot move from {job.status} to {new}")
    job.status = new
    job.updated_at = _now()
    if new != PROCESSING:
        job.claim_token, job.locked_until = None, None
    if new in TERMINAL:
        job.completed_at = _now()
        job.payload = None  # parsed text is never kept once the job cannot run again
        job.next_attempt_at = job.completed_at
    if new == QUEUED:
        job.completed_at = None
    job.error_code = error_code if new in (RETRY_PENDING, FAILED, CANCELLED) else None
    job.error_detail = SAFE_DETAIL.get(error_code or "", None) if job.error_code else None


def _audit(session: Session, job: IngestionJob, action: str, *, actor_id=None, actor_type="user", **details) -> None:
    audit.record(session, tenant_id=job.tenant_id, actor_id=actor_id, actor_type=actor_type, action=action, entity_type="ingestion_job", entity_id=job.id,
                 details={"job_type": job.job_type, "status": job.status, "attempts": job.attempts, "document_id": str(job.document_id) if job.document_id else None, **details},
                 correlation_id=job.correlation_id)


def new_job(session: Session, *, tenant_id, job_type: str, requested_by=None, correlation_id=None, document_id=None, source_version=None, filename=None, kind=None,
            idempotency_key=None, payload=None, config=None, max_attempts=DEFAULT_MAX_ATTEMPTS, initial_failure: str | None = None, source_id=None, connector_id=None, progress=None, endpoint_id=None, job_id=None) -> IngestionJob:
    job = IngestionJob(**({"id": job_id} if job_id else {}), tenant_id=tenant_id, job_type=job_type, status=QUEUED, document_id=document_id, source_version=source_version, filename=filename, kind=kind,
                       attempts=0, max_attempts=max_attempts, idempotency_key=idempotency_key, requested_by=requested_by, correlation_id=correlation_id,
                       payload=payload, processing_config=config or {}, next_attempt_at=_now(), source_id=source_id, connector_id=connector_id, progress=progress, endpoint_id=endpoint_id)
    if initial_failure:  # a rejected upload is recorded as an already failed job
        job.status, job.attempts, job.completed_at, job.payload, job.idempotency_key = FAILED, 1, _now(), None, None
        job.error_code, job.error_detail = initial_failure, SAFE_DETAIL.get(initial_failure)
    session.add(job)
    session.flush()
    _audit(session, job, "ingestion.job_created", actor_id=requested_by)
    if initial_failure:
        _audit(session, job, "ingestion.job_failed", actor_id=requested_by, error_code=initial_failure)
    METRICS.incr("ingestion_jobs_total", tenant=str(tenant_id), job_type=job_type, outcome="created")
    return job


# ------------------------------------------------------------------------------------------------------------------------------------ claiming
def claim(session: Session, job: IngestionJob, *, by: str, lease_seconds: int = LEASE_SECONDS, ignore_schedule: bool = False) -> str | uuid.UUID | None:
    """Claim a job the caller has locked FOR UPDATE. Returns the fencing token, None when it cannot be claimed now (not due, or another claim holds a valid lease), or the string
    "exhausted" when the retry limit is spent (the job is failed here)."""
    now = _now()
    if job.status == PROCESSING:
        if job.locked_until is not None and job.locked_until > now:
            return None
        set_status(job, RETRY_PENDING, error_code="claim_lost")  # a crashed attempt: it counted, the lease expired
        _audit(session, job, "ingestion.attempt_abandoned", actor_type="worker", error_code="claim_lost")
    if job.status not in (QUEUED, RETRY_PENDING):
        return None
    if not ignore_schedule and job.next_attempt_at > now:
        return None
    if job.attempts >= job.max_attempts:
        set_status(job, FAILED, error_code="retries_exhausted")
        _audit(session, job, "ingestion.job_failed", actor_type="worker", error_code="retries_exhausted")
        METRICS.incr("ingestion_jobs_total", tenant=str(job.tenant_id), job_type=job.job_type, outcome="retries_exhausted")
        return "exhausted"
    set_status(job, PROCESSING)
    job.attempts += 1
    job.claim_token = uuid.uuid4()
    job.locked_until = now + dt.timedelta(seconds=lease_seconds)
    job.claimed_by = by
    _audit(session, job, "ingestion.attempt_started", actor_type="worker" if by == "worker" else "user", attempt=job.attempts, claimed_by=by)
    return job.claim_token


@dataclass
class Claimed:
    id: uuid.UUID
    tenant_id: uuid.UUID
    token: uuid.UUID
    job_type: str
    correlation_id: str | None = None


def claim_next(db: Database, lease_seconds: int = LEASE_SECONDS) -> Claimed | None:
    """Worker claim across tenants (the worker policy sees all jobs, like the outbox): FOR UPDATE SKIP LOCKED, due jobs and expired leases only."""
    for _ in range(25):
        with db.session() as s:
            now = _now()
            job = s.scalar(select(IngestionJob).where(or_(and_(IngestionJob.status.in_((QUEUED, RETRY_PENDING)), IngestionJob.next_attempt_at <= now),
                                                          and_(IngestionJob.status == PROCESSING, IngestionJob.locked_until < now)))
                           .order_by(IngestionJob.created_at).limit(1).with_for_update(skip_locked=True))
            if job is None:
                return None
            result = claim(s, job, by="worker", lease_seconds=lease_seconds)
            s.commit()
            if isinstance(result, uuid.UUID):
                return Claimed(job.id, job.tenant_id, result, job.job_type, job.correlation_id)
    return None


def _locked_claimed(session: Session, job_id, token) -> IngestionJob:
    """Lock the job row and prove this caller still owns it (the fencing check). Raises StaleClaim otherwise."""
    job = session.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
    if job is None or job.status != PROCESSING or job.claim_token != token:
        raise StaleClaim()
    return job


# ------------------------------------------------------------------------------------------------------------------------------------ outcomes
def _drop_source(session: Session, job: IngestionJob) -> None:
    """Remove the retained original of a job that will never produce a document version (cancelled, permanently failed, duplicate). A source already linked to a version stays."""
    if job.source_id is not None:
        sources.release(session, tenant_id=job.tenant_id, source_id=job.source_id)
        job.source_id = None


def complete(session: Session, job_id, token, *, outcome: str, chunks=None, from_generation=None, to_generation=None, document_id=None, version=None,
             actor_id=None) -> IngestionJob:
    """Complete the job INSIDE the caller's transaction (the same one that wrote the content): fenced, so a job completes exactly once."""
    job = _locked_claimed(session, job_id, token)
    set_status(job, COMPLETED)
    if outcome == "duplicate":
        _drop_source(session, job)  # the content already exists as a document: the job's own copy is redundant
    job.outcome, job.result_chunks, job.from_generation, job.to_generation = outcome, chunks, from_generation, to_generation
    if document_id:
        job.document_id = document_id if isinstance(document_id, uuid.UUID) else uuid.UUID(str(document_id))
    if version is not None:
        job.source_version = version
    _audit(session, job, "ingestion.job_completed", actor_type="worker" if job.claimed_by == "worker" else "user", actor_id=actor_id, outcome=outcome, chunks=chunks)
    METRICS.incr("ingestion_jobs_total", tenant=str(job.tenant_id), job_type=job.job_type, outcome="completed")
    return job


def retry_later(db: Database, tenant_id, job_id, token, code: str, *, base=BACKOFF_BASE, cap=BACKOFF_CAP) -> str:
    """A transient failure: schedule the next attempt with bounded backoff, or fail with retries_exhausted when the limit is reached. Fenced; returns the new status or 'stale'."""
    try:
        with db.session(tenant_id=tenant_id) as s:
            job = _locked_claimed(s, job_id, token)
            if job.attempts >= job.max_attempts:
                set_status(job, FAILED, error_code="retries_exhausted")
                _audit(s, job, "ingestion.job_failed", actor_type="worker", error_code="retries_exhausted", last_error=code)
                METRICS.incr("ingestion_jobs_total", tenant=str(tenant_id), job_type=job.job_type, outcome="retries_exhausted")
                METRICS.incr("dead_letters_total", tenant=str(tenant_id), source=f"ingestion.{job.job_type}")
            else:
                set_status(job, RETRY_PENDING, error_code=code)
                job.next_attempt_at = _now() + dt.timedelta(seconds=backoff_delay(job.attempts, base, cap))
                _audit(s, job, "ingestion.retry_scheduled", actor_type="worker", error_code=code, next_attempt_at=job.next_attempt_at.isoformat())
                METRICS.incr("ingestion_retries_total", tenant=str(tenant_id), job_type=job.job_type)
            status = job.status
            s.commit()
            return status
    except StaleClaim:
        return "stale"


def fail(db: Database, tenant_id, job_id, token, code: str) -> str:
    try:
        with db.session(tenant_id=tenant_id) as s:
            job = _locked_claimed(s, job_id, token)
            set_status(job, FAILED, error_code=code)
            _drop_source(s, job)  # a permanent failure makes the retained content useless: it is not kept
            _audit(s, job, "ingestion.job_failed", actor_type="worker" if job.claimed_by == "worker" else "user", error_code=code)
            METRICS.incr("ingestion_jobs_total", tenant=str(tenant_id), job_type=job.job_type, outcome="failed")
            METRICS.incr("dead_letters_total", tenant=str(tenant_id), source=f"ingestion.{job.job_type}")
            s.commit()
            return FAILED
    except StaleClaim:
        return "stale"


def cancel_claimed(db: Database, tenant_id, job_id, token, code="document_deleted") -> str:
    try:
        with db.session(tenant_id=tenant_id) as s:
            job = _locked_claimed(s, job_id, token)
            set_status(job, CANCELLED, error_code=code)
            _drop_source(s, job)
            _audit(s, job, "ingestion.job_cancelled", actor_type="worker", error_code=code)
            s.commit()
            return CANCELLED
    except StaleClaim:
        return "stale"


def cancel_for_document(session: Session, *, tenant_id, document_id, actor_id=None, correlation_id=None) -> int:
    """Deletion of a document cancels its active jobs (including one a worker is processing right now: its next fenced write is refused)."""
    jobs = session.scalars(select(IngestionJob).where(IngestionJob.tenant_id == tenant_id, IngestionJob.document_id == document_id,
                                                      IngestionJob.status.in_(ACTIVE)).with_for_update()).all()
    for job in jobs:
        set_status(job, CANCELLED, error_code="document_deleted")
        _drop_source(session, job)
        job.correlation_id = job.correlation_id or correlation_id
        _audit(session, job, "ingestion.job_cancelled", actor_id=actor_id, error_code="document_deleted")
        METRICS.incr("ingestion_jobs_total", tenant=str(tenant_id), job_type=job.job_type, outcome="cancelled")
    return len(jobs)


def classify(exc: BaseException) -> tuple[str, str]:
    """('transient' | 'permanent', error code). Unknown errors are treated as transient but remain bounded by the retry limit."""
    if isinstance(exc, DependencyUnavailable):
        return "transient", "embedding_unavailable"
    from app.connectors.rest_records import (
        SourceError,  # a failure of an external REST source carries its own fixed code and its own retry decision
    )
    if isinstance(exc, SourceError):
        return ("transient" if exc.transient else "permanent"), exc.code
    if isinstance(exc, (OperationalError, TimeoutError, ConnectionError)):
        return "transient", "database_unavailable"
    if isinstance(exc, SourceChanged):
        return "permanent", "source_changed"
    if isinstance(exc, AppError):
        return "permanent", getattr(exc, "code", "invalid")
    return "transient", "unexpected_error"


# ------------------------------------------------------------------------------------------------------------------------------------ uploads
def _payload(parsed: Parsed, media_type: str, size: int, content_hash: str) -> dict:
    return {"segments": [asdict(s) for s in parsed.segments], "page_count": parsed.page_count, "media_type": media_type, "size_bytes": size, "content_hash": content_hash}


def _parsed_from(payload: dict) -> Parsed:
    return Parsed(segments=[Segment(**s) for s in payload["segments"]], page_count=payload.get("page_count"))


def record_rejected_upload(db: Database, *, tenant_id, user_id, filename: str, kind: str, code: str, correlation_id=None) -> None:
    """A permanently failed upload (unsupported or invalid content) is recorded as a FAILED job in its own committed transaction."""
    with db.session(tenant_id=tenant_id, user_id=user_id) as s:
        new_job(s, tenant_id=tenant_id, job_type="ingest", requested_by=user_id, correlation_id=correlation_id, filename=filename, kind=kind, initial_failure=code)
        s.commit()


def _open_inline_job(db: Database, *, tenant_id, user_id, key, filename, kind, original, config, correlation_id, document_id) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create the job (or resume the active job for the same content: duplicate submission), store the ORIGINAL content with it in the same transaction, and claim it for this
    request. Returns (job id, fencing token, source id). Source persistence failing aborts everything: no job, no source, a 503 (nothing was accepted)."""
    for _ in range(5):
        try:
            with db.session(tenant_id=tenant_id, user_id=user_id) as s:
                job = s.scalar(select(IngestionJob).where(IngestionJob.tenant_id == tenant_id, IngestionJob.idempotency_key == key, IngestionJob.status.in_(ACTIVE)).with_for_update())
                if job is None:
                    job = new_job(s, tenant_id=tenant_id, job_type="ingest", requested_by=user_id, correlation_id=correlation_id, filename=filename, kind=kind,
                                  idempotency_key=key, config=config, document_id=document_id)
                if job.source_id is None:  # a new job, or an older one created before sources were retained: identical content, so this copy is what a retry uses
                    job.source_id = sources.store(s, tenant_id=tenant_id, filename=filename, kind=kind, **original)
                token = claim(s, job, by="api", ignore_schedule=True)
                s.commit()
                if isinstance(token, uuid.UUID):
                    return job.id, token, job.source_id
                if token is None:
                    raise DependencyUnavailable("This content is already being processed; retry shortly", code="ingestion_in_progress", retry_after=5)
                # "exhausted": that job is now FAILED; the loop creates a fresh one
        except IntegrityError:
            continue  # a concurrent request created the active job first: re-read it
    raise DependencyUnavailable("Could not open an ingestion job; retry shortly", code="ingestion_in_progress", retry_after=5)


def run_upload(db: Database, session: Session, *, tenant_id, user_id, filename: str, data: bytes, kind: str, embedder: Embedder, field_map=None, id_field=None,
               correlation_id=None, extra_kinds=frozenset()) -> IngestResult:
    """Synchronous upload with a persistent record (the public contract is unchanged: 201 with the same body on success, the same errors otherwise).

    Success: document, version, chunks and the job completion commit together (the caller commits `session`). A transient failure leaves the job RETRY_PENDING with the parsed
    segments (the worker finishes it, or a repeated upload resumes it) and raises the same 503 as before. A permanent failure is recorded FAILED and raises the same error."""
    if kind not in DOCUMENT_KINDS and kind not in extra_kinds:
        raise Invalid(f"Unknown document kind '{kind}'", code="invalid_kind")
    filename = safe_filename(filename)
    content_hash = hashlib.sha256(data).hexdigest()
    found = find_duplicate(session, tenant_id=tenant_id, user_id=user_id, filename=filename, content_hash=content_hash, correlation_id=correlation_id)
    if found:
        return found
    try:
        parsed, media_type = parse(filename, data, field_map=field_map, id_field=id_field)
    except AppError as exc:
        session.rollback()
        record_rejected_upload(db, tenant_id=tenant_id, user_id=user_id, filename=filename, kind=kind, code=getattr(exc, "code", "invalid"), correlation_id=correlation_id)
        raise
    require_compatible(session, tenant_id, embedder)
    existing = session.scalar(select(Document.id).where(Document.tenant_id == tenant_id, Document.source_key == filename.lower(), Document.lifecycle_status == "active"))
    started = time.perf_counter()
    original = dict(media_type=media_type, data=data, content_hash=content_hash, parse_options={"field_map": field_map, "id_field": id_field})
    opened = dict(tenant_id=tenant_id, user_id=user_id, key=f"ingest:{content_hash}", filename=filename, kind=kind, original=original,
                  config=processing_config(embedder), correlation_id=correlation_id, document_id=existing)
    deadline = time.monotonic() + INFLIGHT_WAIT_SECONDS
    while True:
        try:
            job_id, token, source_id = _open_inline_job(db, **opened)
            break
        except DependencyUnavailable as exc:
            if getattr(exc, "code", None) != "ingestion_in_progress" or time.monotonic() >= deadline:
                raise
            # another request is processing the same content: wait for it and resolve to its result, exactly as a sequential repeat upload would (the pre-job contract: 201 duplicate)
            time.sleep(0.2)
            session.rollback()
            found = find_duplicate(session, tenant_id=tenant_id, user_id=user_id, filename=filename, content_hash=content_hash, correlation_id=correlation_id)
            if found:
                return found
    try:
        vectors = embed_segments(embedder, kind, filename, parsed.segments)
    except DependencyUnavailable:
        retry_later(db, tenant_id, job_id, token, "embedding_unavailable")
        raise
    try:
        result = store_parsed(session, tenant_id=tenant_id, user_id=user_id, filename=filename, kind=kind, content_hash=content_hash, size_bytes=len(data), media_type=media_type,
                              parsed=parsed, vectors=vectors, embedder=embedder, correlation_id=correlation_id, job_id=job_id, source_id=source_id)
        complete(session, job_id, token, outcome=result.status, chunks=result.chunk_count, document_id=result.document_id, version=result.version, actor_id=user_id)
        session.flush()
        METRICS.observe("ingestion_job_seconds", time.perf_counter() - started, tenant=str(tenant_id), job_type="ingest")
        return result
    except IntegrityError:  # a concurrent upload of the same content won the race: resolve to its result (idempotent outcome)
        session.rollback()
        dup = find_duplicate(session, tenant_id=tenant_id, user_id=user_id, filename=filename, content_hash=content_hash, correlation_id=correlation_id)
        if dup is None:
            raise
        _finish_duplicate(db, tenant_id, job_id, token, dup)
        return dup
    except StaleClaim:
        session.rollback()
        raise DependencyUnavailable("This content is being processed elsewhere; retry shortly", code="ingestion_in_progress", retry_after=5) from None
    except AppError as exc:
        session.rollback()
        fail(db, tenant_id, job_id, token, getattr(exc, "code", "invalid"))
        raise


def _finish_duplicate(db: Database, tenant_id, job_id, token, dup: IngestResult) -> None:
    try:
        with db.session(tenant_id=tenant_id) as s:
            complete(s, job_id, token, outcome="duplicate", chunks=dup.chunk_count, document_id=dup.document_id, version=dup.version)
            s.commit()
    except StaleClaim:
        pass


# ------------------------------------------------------------------------------------------------------------------------------------ reprocessing
def request_reprocess(session: Session, *, tenant_id, user_id, document_id, embedder: Embedder, correlation_id=None) -> IngestionJob:
    """Queue a reprocessing job for an ACTIVE document. Duplicate requests while one is active return that job (idempotent). Unknown, other-tenant and deleted documents are 404."""
    doc = session.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id, Document.lifecycle_status == "active").with_for_update())
    if doc is None:
        raise NotFound("Document not found")
    version = session.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.version == doc.current_version))
    if version is None or version.source_id is None:  # documents stored before original content was retained cannot be reprocessed from source: stated, not faked
        raise Conflict("The original file of this document was not retained (it was uploaded before source storage existed); upload the file again to enable reprocessing", code="source_not_retained")
    key = f"reprocess:{doc.id}"
    existing = session.scalar(select(IngestionJob).where(IngestionJob.tenant_id == tenant_id, IngestionJob.idempotency_key == key, IngestionJob.status.in_(ACTIVE)))
    if existing is not None:
        return existing
    job = new_job(session, tenant_id=tenant_id, job_type="reprocess", requested_by=user_id, correlation_id=correlation_id, document_id=doc.id, source_version=doc.current_version,
                  filename=doc.filename, kind=doc.kind, idempotency_key=key, config=processing_config(embedder))
    job.from_generation = version.active_generation if version else None
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="document.reprocess_requested", entity_type="document", entity_id=doc.id,
                 details={"job_id": str(job.id), "source_version": doc.current_version, "from_generation": job.from_generation, "processing_config": job.processing_config},
                 correlation_id=correlation_id)
    session.flush()
    return job


def request_retry(session: Session, *, tenant_id, user_id, job_id, correlation_id=None) -> IngestionJob:
    """Authorised manual retry of a FAILED reprocessing job (its source is the stored content). A failed upload cannot be retried this way: its parsed text is not kept."""
    job = session.scalar(select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.tenant_id == tenant_id).with_for_update())
    if job is None:
        raise NotFound("Ingestion job not found")
    if job.status != FAILED:
        raise Conflict(f"Only a failed job can be retried (this one is {job.status})", code="job_not_retryable")
    if job.job_type == "ingest":
        if job.source_id is None:  # rejected uploads (permanent failure) and jobs from before sources were retained keep no content
            raise Conflict("The uploaded content of this failed upload is not retained; upload the document again", code="source_not_retained")
        if job.idempotency_key and session.scalar(select(IngestionJob.id).where(IngestionJob.tenant_id == tenant_id, IngestionJob.idempotency_key == job.idempotency_key,
                                                                               IngestionJob.status.in_(ACTIVE))):
            raise Conflict("The same content is already being processed", code="job_not_retryable")
    elif job.job_type == "sync":
        from app.models import Connector
        if session.scalar(select(Connector.id).where(Connector.id == job.connector_id, Connector.tenant_id == tenant_id)) is None:
            raise Conflict("The connector no longer exists", code="job_not_retryable")
        if session.scalar(select(IngestionJob.id).where(IngestionJob.tenant_id == tenant_id, IngestionJob.idempotency_key == job.idempotency_key, IngestionJob.status.in_(ACTIVE))):
            raise Conflict("A synchronisation of this connector is already active", code="job_not_retryable")
    else:
        doc = session.scalar(select(Document).where(Document.id == job.document_id, Document.tenant_id == tenant_id, Document.lifecycle_status == "active"))
        if doc is None:
            raise Conflict("The document no longer exists", code="job_not_retryable")
    set_status(job, QUEUED)
    job.attempts, job.next_attempt_at, job.requested_by = 0, _now(), user_id
    job.correlation_id = correlation_id or job.correlation_id
    _audit(session, job, "ingestion.job_retry_requested", actor_id=user_id)
    session.flush()
    return job


def _reprocess_read(db: Database, claimed: Claimed) -> tuple[dict, list[Segment]]:
    """Genuine source reprocessing: read the ORIGINAL file retained for the current version, verify its integrity, and re-run the supported parser. Nothing is read from the old chunks."""
    with db.session(tenant_id=claimed.tenant_id) as s:
        job = _locked_claimed(s, claimed.id, claimed.token)
        doc = s.scalar(select(Document).where(Document.id == job.document_id, Document.tenant_id == claimed.tenant_id))
        if doc is None or doc.lifecycle_status != "active":
            raise JobCancelled()
        version = s.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.version == doc.current_version))
        if version is None or version.source_id is None:
            raise sources.SourceMissing("The original content of this document is not retained")
        original = sources.load(s, tenant_id=claimed.tenant_id, source_id=version.source_id)  # SourceMissing or SourceCorrupted (permanent) otherwise
        if original.content_hash != version.content_hash:
            raise sources.SourceCorrupted("The retained original does not belong to this version")
        parsed, _ = parse(doc.filename, original.data, field_map=original.parse_options.get("field_map"), id_field=original.parse_options.get("id_field"))
        info = {"filename": doc.filename, "kind": doc.kind, "version": doc.current_version, "version_id": version.id, "generation": version.active_generation}
        return info, parsed.segments


def _reprocess_write(db: Database, claimed: Claimed, info: dict, segments: list[Segment], vectors: list, embedder: Embedder) -> dict:
    """Stage the replacement generation (not current, so retrieval cannot see it), validate it, then activate it and retire the old one, all in one transaction with the
    job completion. Any failure rolls back and leaves the previously active generation untouched."""
    with db.session(tenant_id=claimed.tenant_id) as s:
        job = _locked_claimed(s, claimed.id, claimed.token)
        doc = s.scalar(select(Document).where(Document.id == job.document_id, Document.tenant_id == claimed.tenant_id).with_for_update())
        if doc is None or doc.lifecycle_status != "active":  # the activation boundary re-checks the lifecycle: a deleted document is never revived
            raise JobCancelled()
        version = s.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.version == doc.current_version).with_for_update())
        if version is None or version.id != info["version_id"] or version.active_generation != info["generation"]:
            raise SourceChanged()
        profile = ensure_active_profile(s, claimed.tenant_id, embedder)
        old_generation, new_generation = version.active_generation, version.active_generation + 1
        for index, (segment, vector) in enumerate(zip(segments, vectors, strict=True)):
            s.add(DocumentChunk(tenant_id=claimed.tenant_id, document_id=doc.id, version_id=version.id, version=version.version, chunk_index=index, text=segment.text,
                                page_number=segment.page_number, record_id=segment.record_id, suspicious=looks_like_injection(segment.text), is_current=False,
                                generation=new_generation, embedding=vector, embedding_profile_id=profile.id))
        s.flush()
        staged = s.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.version_id == version.id, DocumentChunk.generation == new_generation,
                                                                                  DocumentChunk.embedding.is_not(None)))
        if staged != len(segments) or not segments or any(v is None for v in vectors):  # validation before activation
            raise RuntimeError("replacement content failed validation")
        s.execute(update(DocumentChunk).where(DocumentChunk.version_id == version.id, DocumentChunk.generation == old_generation).values(is_current=False))
        s.execute(update(DocumentChunk).where(DocumentChunk.version_id == version.id, DocumentChunk.generation == new_generation).values(is_current=True))
        version.active_generation, version.processing_job_id, version.embedding_backend, version.chunk_count = new_generation, job.id, embedder.name, staged
        audit.record(s, tenant_id=claimed.tenant_id, actor_id=job.requested_by, action="document.reprocessed", entity_type="document", entity_id=doc.id,
                     details={"job_id": str(job.id), "version": version.version, "from_generation": old_generation, "to_generation": new_generation, "chunks": staged,
                              "processing_config": job.processing_config}, correlation_id=job.correlation_id)
        complete(s, claimed.id, claimed.token, outcome="reprocessed", chunks=staged, from_generation=old_generation, to_generation=new_generation, document_id=doc.id,
                 version=version.version, actor_id=job.requested_by)
        s.commit()
        return {"from_generation": old_generation, "to_generation": new_generation, "chunks": staged}


def _ingest_write(db: Database, claimed: Claimed, parsed: Parsed, meta: dict, vectors: list, embedder: Embedder, filename: str, kind: str, user_id, source_id=None) -> IngestResult:
    with db.session(tenant_id=claimed.tenant_id) as s:
        _locked_claimed(s, claimed.id, claimed.token)
        dup = find_duplicate(s, tenant_id=claimed.tenant_id, user_id=user_id, filename=filename, content_hash=meta["content_hash"])
        if dup is not None:  # the same content was stored meanwhile (a client's repeated upload): the outcome is the existing document, never a second copy
            complete(s, claimed.id, claimed.token, outcome="duplicate", chunks=dup.chunk_count, document_id=dup.document_id, version=dup.version, actor_id=user_id)
            s.commit()
            return dup
        result = store_parsed(s, tenant_id=claimed.tenant_id, user_id=user_id, filename=filename, kind=kind, content_hash=meta["content_hash"], size_bytes=meta["size_bytes"],
                              media_type=meta["media_type"], parsed=parsed, vectors=vectors, embedder=embedder, job_id=claimed.id, source_id=source_id)
        complete(s, claimed.id, claimed.token, outcome=result.status, chunks=result.chunk_count, document_id=result.document_id, version=result.version, actor_id=user_id)
        s.commit()
        return result


def execute(db: Database, claimed: Claimed, embedder: Embedder, backoff_base: float = BACKOFF_BASE, backoff_cap: float = BACKOFF_CAP) -> str:
    """Run one claimed job to an outcome string: completed | retry_scheduled | failed | cancelled | stale. Never raises for expected failures; a BaseException (a crash) leaves the
    job PROCESSING so the lease expires and it is reclaimed."""
    from app.connectors.ratelimit import LIMITERS
    from app.observability import tracing

    if LIMITERS.database is None:  # a worker process: share connector limits with the API through the same database
        LIMITERS.use_database(db)
    trace_token = tracing.set_current(tracing.trace_id_for(claimed.correlation_id))
    try:
        with tracing.span("ingestion.job", job_type=claimed.job_type, tenant_id=str(claimed.tenant_id)) as attrs:
            outcome = _execute(db, claimed, embedder, backoff_base, backoff_cap)
            attrs["outcome"] = outcome
            return outcome
    finally:
        tracing.reset(trace_token)


def _execute(db: Database, claimed: Claimed, embedder: Embedder, backoff_base: float, backoff_cap: float) -> str:
    started = time.perf_counter()
    try:
        if claimed.job_type in ("sync", "webhook"):
            from app.ingestion import sync
            sync.run(db, claimed, embedder)
        elif claimed.job_type == "reprocess":
            info, segments = _reprocess_read(db, claimed)
            vectors = embed_segments(embedder, info["kind"], info["filename"], segments)
            _reprocess_write(db, claimed, info, segments, vectors, embedder)
        else:
            with db.session(tenant_id=claimed.tenant_id) as s:
                job = _locked_claimed(s, claimed.id, claimed.token)
                payload, filename, kind, user_id, source_id = job.payload, job.filename, job.kind, job.requested_by, job.source_id
                original = sources.load(s, tenant_id=claimed.tenant_id, source_id=source_id) if source_id else None  # integrity verified on every read
                if job.document_id is not None:  # a document deleted since the upload cancels the job instead of storing late content
                    doc = s.scalar(select(Document).where(Document.id == job.document_id, Document.tenant_id == claimed.tenant_id))
                    if doc is not None and doc.lifecycle_status != "active":
                        raise JobCancelled()
            if original is not None:  # the normal path: re-run the supported parser on the retained original
                parsed, _ = parse(original.filename, original.data, field_map=original.parse_options.get("field_map"), id_field=original.parse_options.get("id_field"))
                meta = {"content_hash": original.content_hash, "size_bytes": original.size_bytes, "media_type": original.media_type}
            elif payload:  # a job created before 0011: the parsed segments it saved
                parsed, meta = _parsed_from(payload), payload
            else:
                raise AppError("The content of this upload is no longer available", code="source_not_retained")
            vectors = embed_segments(embedder, kind, filename, parsed.segments)
            _ingest_write(db, claimed, parsed, meta, vectors, embedder, filename, kind, user_id, source_id=source_id)
        METRICS.observe("ingestion_job_seconds", time.perf_counter() - started, tenant=str(claimed.tenant_id), job_type=claimed.job_type)
        return "completed"
    except StaleClaim:
        return "stale"
    except JobCancelled:
        cancel_claimed(db, claimed.tenant_id, claimed.id, claimed.token)
        return "cancelled"
    except Exception as exc:  # noqa: BLE001 - classified below; only the CODE is stored, never the message
        kind_of, code = classify(exc)
        log_event(log, "ingestion.job_error", level=logging.WARNING, job_id=str(claimed.id), tenant_id=str(claimed.tenant_id), error_class=type(exc).__name__, error_code=code)
        if kind_of == "transient":
            status = retry_later(db, claimed.tenant_id, claimed.id, claimed.token, code, base=backoff_base, cap=backoff_cap)
            return "stale" if status == "stale" else ("failed" if status == FAILED else "retry_scheduled")
        return "stale" if fail(db, claimed.tenant_id, claimed.id, claimed.token, code) == "stale" else "failed"


def _sync_summary(job: IngestionJob):
    from app.ingestion import sync
    return sync.summary(job)


def job_out(job: IngestionJob) -> dict:
    cfg = job.processing_config or {}
    return {"id": str(job.id), "job_type": job.job_type, "status": job.status, "document_id": str(job.document_id) if job.document_id else None,
            "filename": job.filename, "source_version": job.source_version, "attempts": job.attempts, "max_attempts": job.max_attempts,
            "next_attempt_at": job.next_attempt_at.isoformat() if job.status in (QUEUED, RETRY_PENDING) else None, "error_code": job.error_code, "error_detail": job.error_detail,
            "outcome": job.outcome, "chunks": job.result_chunks, "from_generation": job.from_generation, "to_generation": job.to_generation,
            "connector_id": str(job.connector_id) if job.connector_id else None, "endpoint_id": str(job.endpoint_id) if job.endpoint_id else None,
            "sync": _sync_summary(job),
            "requested_by": str(job.requested_by) if job.requested_by else None, "correlation_id": job.correlation_id,
            "processing_config": {"embedding_backend": cfg.get("embedding_backend"), "embedding_model": cfg.get("embedding_model"), "index_prefix": cfg.get("index_prefix"),
                                  "safety_heuristics": cfg.get("safety_heuristics")},
            "created_at": job.created_at.isoformat(), "updated_at": job.updated_at.isoformat(), "completed_at": job.completed_at.isoformat() if job.completed_at else None}
