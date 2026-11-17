"""REST pull synchronization (V41-12.01 REST part, V41-11.01, V41-11.02): a durable `sync` job that pulls records from a tenant's REST connector and ingests them.

It reuses everything that exists: the `ingestion_jobs` table and state machine (fenced claim and lease, bounded backoff, audit), the worker loop, the connector HTTP client with its egress policy,
the JSON parser, embeddings, `store_parsed`, retained original sources and deletion cleanup. This module adds only the orchestration:

* `request_sync` commits the job (idempotent: one active sync per connector) and the API answers 202 only after that commit;
* `run` pulls page by page (bounded), processes every valid record in its OWN fenced transaction, and saves the pager position and counts after each page, so a retry resumes;
* `connector_sync_records` is the idempotency and provenance record: unchanged content is skipped, changed content becomes a new version of the same document, identical content that already
  exists elsewhere is linked rather than duplicated, and a document a user deleted stays deleted until the source record's content changes;
* success is recorded only after every page was processed.
Failures carry fixed codes only; nothing from the upstream response, no header and no credential is ever stored or logged."""
import hashlib
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.connectors.egress import EgressDenied, get_policy, tenant_slug
from app.connectors.rest_records import (
    PageState,
    RecordInvalid,
    SourceError,
    build_csv_source,
    build_source,
    document_name,
    parse_config,
    parse_csv_config,
    validate_record,
)
from app.core.errors import AppError, Conflict, Invalid, NotFound
from app.database.session import Database
from app.ingestion import jobs, sources
from app.ingestion.parsers import parse
from app.ingestion.service import DOCUMENT_KINDS, embed_segments, find_duplicate, store_parsed
from app.models import Connector, ConnectorSyncRecord, Document, IngestionJob, WebhookEndpoint
from app.observability.logging import log_event

log = logging.getLogger("eaop.sync")

SHUTDOWN = threading.Event()  # set when the worker process is stopping: waits for rate-limit tokens end at once
HEARTBEAT_SECONDS = 180  # lease extension before each page: a page may wait for a rate-limit token or an upstream Retry-After
COUNTERS = ("pages", "seen", "created", "updated", "unchanged", "linked_duplicate", "skipped_deleted", "tombstoned_changed", "duplicate_in_sync", "conflict", "invalid")


def _blank_progress() -> dict:
    return {"pager": PageState().to_json(), "counts": dict.fromkeys(COUNTERS, 0), "rejections": {}, "truncated": False}


@dataclass
class ConnectorInfo:
    """The origin of a stream of records: a REST or CSV connector (`origin` connector) or a webhook endpoint (`origin` endpoint)."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    base_url: str
    secret_ref: str | None
    config: dict
    kind: str = "rest"  # rest | csv | webhook
    origin: str = "connector"  # connector | endpoint

    @property
    def prefix(self) -> str:
        return {"rest": "rest", "csv": "csv", "webhook": "webhook"}[self.kind]

    def key_filter(self) -> list:
        return [ConnectorSyncRecord.endpoint_id == self.id] if self.origin == "endpoint" else [ConnectorSyncRecord.connector_id == self.id]


class WebhookRecordsConfig(BaseModel):
    """`config` of a webhook endpoint: how records are found in a delivery and how they are validated (the same rules as REST records)."""
    model_config = ConfigDict(extra="forbid")
    record_path: str | None = None  # None: the body is one record (an object) or a list of records
    id_field: str
    version_field: str | None = None
    required_fields: list[str] = Field(default_factory=list, max_length=20)
    document_kind: str = "other"
    max_records: int = Field(default=100, ge=1, le=1000)
    max_record_bytes: int = Field(default=65536, ge=256, le=262144)
    reject_policy: str = Field(default="skip", pattern="^(skip|fail)$")

    @model_validator(mode="after")
    def _safe(self):
        for name in (self.record_path, self.id_field, self.version_field, *self.required_fields):
            if name is not None and not _FIELD.match(name):
                raise ValueError("invalid field name")
        return self



_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]{0,59}$")


def parse_webhook_config(config: dict | None) -> WebhookRecordsConfig:
    try:
        return WebhookRecordsConfig.model_validate(config or {})
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) or "config" for e in exc.errors()})
        raise Invalid(f"Invalid webhook configuration (check: {', '.join(fields)})", code="invalid_connector_config", status_code=422) from exc


def webhook_records(body, cfg: WebhookRecordsConfig) -> list:
    """The records of a delivery. Raises Invalid(invalid_payload) for a shape that can never be processed (checked BEFORE the delivery is acknowledged)."""
    data = body
    if cfg.record_path is not None:
        data = body.get(cfg.record_path) if isinstance(body, dict) else None
        if not isinstance(data, (list, dict)):
            raise Invalid("The payload does not contain the configured record list", code="invalid_payload", status_code=422)
    records = data if isinstance(data, list) else [data]
    if not records or len(records) > cfg.max_records or not all(isinstance(r, dict) for r in records):
        raise Invalid("The payload must contain between 1 and the configured maximum of record objects", code="invalid_payload", status_code=422)
    return records


# ------------------------------------------------------------------------------------------------------------------------------------ request
def request_sync(session, *, tenant_id, user_id, connector_id, embedder, allowed_kinds=frozenset(), correlation_id=None) -> IngestionJob:
    """Commit-ready sync job for a connector of THIS tenant. Unknown and other-tenant ids are 404. A second request while one is active returns that job (nothing is queued twice)."""
    connector = session.scalar(select(Connector).where(Connector.id == connector_id, Connector.tenant_id == tenant_id))
    if connector is None:
        raise NotFound("Connector not found")
    if connector.kind not in ("rest", "csv"):
        raise Invalid("Only a REST or CSV connector with its configuration can be synchronised", code="invalid_connector_config", status_code=409)
    try:
        cfg = parse_config(connector.config) if connector.kind == "rest" else parse_csv_config(connector.config)
    except Invalid as exc:  # the connector is not in a state that can be synchronised: a conflict with the resource, not a malformed request
        raise Invalid(str(exc), code=exc.code, status_code=409) from exc
    if cfg.document_kind not in DOCUMENT_KINDS and cfg.document_kind not in allowed_kinds:
        raise Invalid("The configured document kind is not allowed for this tenant", code="invalid_connector_config", status_code=409)
    try:  # fail fast: a destination the server does not approve for this tenant would only fail the job later
        get_policy().check_config(connector.base_url, tenant_slug(session, tenant_id))
    except EgressDenied as exc:
        raise Invalid(f"Connector destination rejected: {exc.reason}", code="connector_destination_not_allowed", status_code=409) from exc
    key = f"sync:{connector.id}"
    existing = session.scalar(select(IngestionJob).where(IngestionJob.tenant_id == tenant_id, IngestionJob.idempotency_key == key, IngestionJob.status.in_(jobs.ACTIVE)))
    if existing is not None:
        return existing
    job = jobs.new_job(session, tenant_id=tenant_id, job_type="sync", requested_by=user_id, correlation_id=correlation_id, filename=connector.name, kind=cfg.document_kind,
                       idempotency_key=key, config=jobs.processing_config(embedder), connector_id=connector.id, progress=_blank_progress())
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="connector.sync_requested", entity_type="connector", entity_id=connector.id,
                 details={"job_id": str(job.id), "kind": connector.kind, **({"pagination": cfg.pagination.mode, "max_pages": cfg.max_pages, "max_records": cfg.max_records} if connector.kind == "rest" else {"max_rows": cfg.max_rows})},
                 correlation_id=correlation_id)
    session.flush()
    return job


# ------------------------------------------------------------------------------------------------------------------------------------ execution
def _save_progress(db: Database, claimed, progress: dict) -> None:
    with db.session(tenant_id=claimed.tenant_id) as s:
        job = jobs._locked_claimed(s, claimed.id, claimed.token)  # fenced: a worker that lost its lease can not overwrite newer state
        job.progress = progress
        s.commit()


def heartbeat(db: Database, claimed, seconds: int = HEARTBEAT_SECONDS) -> None:
    with db.session(tenant_id=claimed.tenant_id) as s:
        job = jobs._locked_claimed(s, claimed.id, claimed.token)
        job.locked_until = jobs._now() + jobs.dt.timedelta(seconds=seconds)
        s.commit()


def _load(db: Database, claimed) -> tuple[ConnectorInfo, dict, str | None, uuid.UUID | None, str]:
    with db.session(tenant_id=claimed.tenant_id) as s:
        job = jobs._locked_claimed(s, claimed.id, claimed.token)
        if job.job_type == "webhook":
            ep = s.scalar(select(WebhookEndpoint).where(WebhookEndpoint.id == job.endpoint_id, WebhookEndpoint.tenant_id == claimed.tenant_id))
            if ep is None:
                raise AppError("The webhook endpoint no longer exists", code="connector_not_found")
            info = ConnectorInfo(ep.id, ep.tenant_id, ep.name, "", None, dict(ep.config or {}), kind="webhook", origin="endpoint")
            return info, dict(job.progress or _blank_progress()), None, job.requested_by, job.kind
        row = s.scalar(select(Connector).where(Connector.id == job.connector_id, Connector.tenant_id == claimed.tenant_id))
        if row is None:
            raise AppError("The connector no longer exists", code="connector_not_found")
        info = ConnectorInfo(row.id, row.tenant_id, row.name, row.base_url, row.secret_ref, dict(row.config or {}), kind=row.kind)
        return info, dict(job.progress or _blank_progress()), tenant_slug(s, claimed.tenant_id), job.requested_by, job.kind


def run(db: Database, claimed, embedder, stop: threading.Event | None = None) -> None:
    """Execute one claimed `sync` job (REST or CSV connector) or `webhook` job. Raises SourceError (fixed code; `transient` decides retry versus failure), StaleClaim or JobCancelled
    like the other job types."""
    stop = stop or SHUTDOWN
    info, progress, slug, user_id, kind = _load(db, claimed)
    if info.kind == "webhook":
        return _run_webhook(db, claimed, info, user_id, kind, embedder)
    if info.kind == "csv":
        cfg = parse_csv_config(info.config)  # re-validated at execution: a connector edited since the request cannot widen what the job does
        source = build_csv_source(_row_of(info), cfg, tenant_slug=slug, stop=stop)
    else:
        cfg = parse_config(info.config)
        source = build_source(_row_of(info), cfg, tenant_slug=slug, stop=stop)
    state = PageState.from_json(progress.get("pager"))
    counts = {**dict.fromkeys(COUNTERS, 0), **progress.get("counts", {})}
    rejections = dict(progress.get("rejections", {}))
    seen: dict[str, str] = {}
    truncated = bool(progress.get("truncated"))
    while not state.done:
        if stop.is_set():
            raise SourceError("worker_stopping", transient=True)
        heartbeat(db, claimed)
        page = source.fetch_page(state)
        if page.malformed:  # CSV rows with the wrong number of cells or invalid quoting: rejected and counted, never guessed
            counts["invalid"] += page.malformed
            rejections["malformed_row"] = rejections.get("malformed_row", 0) + page.malformed
        for index, record in enumerate(page.records):
            counts["seen"] += 1
            row_number = page.row_numbers[index] if page.row_numbers else None
            outcome = _ingest_record(db, claimed, info, cfg, record, kind, user_id, embedder, seen, rejections, row_number)
            counts[outcome] += 1
            if outcome == "invalid" and cfg.reject_policy == "fail":
                _save_progress(db, claimed, {"pager": state.to_json(), "counts": counts, "rejections": rejections, "truncated": truncated})
                raise SourceError("source_record_invalid")
        if page.malformed and cfg.reject_policy == "fail":
            _save_progress(db, claimed, {"pager": state.to_json(), "counts": counts, "rejections": rejections, "truncated": truncated})
            raise SourceError("source_record_invalid")
        state, truncated = page.state, truncated or page.truncated
        counts["pages"] = state.pages
        _save_progress(db, claimed, {"pager": state.to_json(), "counts": counts, "rejections": rejections, "truncated": truncated})
    _finish(db, claimed, info, user_id, state, counts, rejections, truncated)


def _row_of(info: ConnectorInfo):
    return type("Row", (), {"base_url": info.base_url, "secret_ref": info.secret_ref, "tenant_id": info.tenant_id, "id": info.id})


def _finish(db, claimed, info, user_id, state, counts, rejections, truncated) -> None:
    with db.session(tenant_id=claimed.tenant_id) as s:  # success is recorded only here, after every page (or every record of a delivery) was processed
        job = jobs._locked_claimed(s, claimed.id, claimed.token)
        outcome = "synced_truncated" if truncated else ("synced_with_rejections" if counts["invalid"] or counts["conflict"] else "synced")
        jobs.complete(s, claimed.id, claimed.token, outcome=outcome, chunks=counts["created"] + counts["updated"], actor_id=user_id)
        job.progress = {"pager": state.to_json(), "counts": counts, "rejections": rejections, "truncated": truncated}
        if info.kind == "webhook":
            jobs._drop_source(s, job)  # every record has its own retained original now: the raw delivery body is not kept
        audit.record(s, tenant_id=claimed.tenant_id, actor_type="worker", action="webhook.delivery_processed" if info.kind == "webhook" else "connector.sync_completed",
                     entity_type="webhook_endpoint" if info.kind == "webhook" else "connector", entity_id=info.id,
                     details={"job_id": str(job.id), "outcome": outcome, **{k: v for k, v in counts.items()}}, correlation_id=job.correlation_id)
        s.commit()
    log_event(log, "webhook.delivery_processed" if info.kind == "webhook" else "connector.sync_completed", job_id=str(claimed.id), tenant_id=str(claimed.tenant_id), outcome=outcome,
              **{f"n_{k}": v for k, v in counts.items()})  # prefixed: a bare key such as "created" collides with LogRecord


def _run_webhook(db, claimed, info, user_id, kind, embedder) -> None:
    """Process one accepted webhook delivery: its raw body was stored (checksum verified on read) in the transaction that accepted it. The records go through the same per-record
    pipeline as REST and CSV (idempotency, provenance, tombstones, retained originals)."""
    heartbeat(db, claimed)
    with db.session(tenant_id=claimed.tenant_id) as s:
        job = jobs._locked_claimed(s, claimed.id, claimed.token)
        if job.source_id is None:
            raise AppError("The delivery body is no longer retained", code="source_not_retained")
        original = sources.load(s, tenant_id=claimed.tenant_id, source_id=job.source_id)
    cfg = parse_webhook_config(info.config)
    try:
        records = webhook_records(json.loads(original.data), cfg)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceError("source_schema_invalid") from exc
    except Invalid as exc:
        raise SourceError("source_schema_invalid") from exc
    counts, rejections, seen = dict.fromkeys(COUNTERS, 0), {}, {}
    for record in records:
        counts["seen"] += 1
        outcome = _ingest_record(db, claimed, info, cfg, record, kind, user_id, embedder, seen, rejections, None)
        counts[outcome] += 1
        if outcome == "invalid" and cfg.reject_policy == "fail":
            raise SourceError("source_record_invalid")
    counts["pages"] = 1
    _finish(db, claimed, info, user_id, PageState(pages=1, records=len(records), done=True), counts, rejections, False)


def _ingest_record(db, claimed, info, cfg, record, kind, user_id, embedder, seen: dict, rejections: dict, row_number: int | None = None) -> str:
    try:
        record_id, version, data = validate_record(record, cfg)
    except RecordInvalid as exc:
        rejections[exc.reason] = rejections.get(exc.reason, 0) + 1
        return "invalid"
    content_hash = hashlib.sha256(data).hexdigest()
    if record_id in seen:  # the source repeated an id inside one synchronisation
        previous = seen[record_id]
        return "duplicate_in_sync" if previous == content_hash else "conflict"  # different content under one id: the first is kept, the conflict is counted
    seen[record_id] = content_hash
    name = document_name(info.name, record_id, info.prefix)
    try:
        parsed, media_type = parse(name, data, id_field=cfg.id_field)
    except AppError:
        rejections["unparseable"] = rejections.get("unparseable", 0) + 1
        return "invalid"
    with db.session(tenant_id=claimed.tenant_id) as s:  # cheap pre-check so unchanged records are never embedded again
        row = s.scalar(select(ConnectorSyncRecord).where(ConnectorSyncRecord.tenant_id == claimed.tenant_id, *info.key_filter(), ConnectorSyncRecord.source_record_id == record_id))
        skip = row is not None and (row.content_hash == content_hash or row.status == "deleted")  # nothing to embed for an unchanged record or a deleted one
    vectors = [] if skip else embed_segments(embedder, kind, name, parsed.segments)  # DependencyUnavailable propagates: transient, the job retries the page (idempotent by hash)
    return _write_record(db, claimed, info, cfg, record_id, version, content_hash, data, name, kind, user_id, parsed, media_type, vectors, embedder, row_number)


def _write_record(db, claimed, info, cfg, record_id, version, content_hash, data, name, kind, user_id, parsed, media_type, vectors, embedder, row_number=None) -> str:
    for _ in range(2):  # a concurrent first insert of the same key retries once as an update
        try:
            with db.session(tenant_id=claimed.tenant_id) as s:
                job = jobs._locked_claimed(s, claimed.id, claimed.token)  # fenced
                row = s.scalar(select(ConnectorSyncRecord).where(ConnectorSyncRecord.tenant_id == claimed.tenant_id, *info.key_filter(),
                                                                 ConnectorSyncRecord.source_record_id == record_id).with_for_update())
                if row is not None:
                    doc = s.scalar(select(Document).where(Document.id == row.document_id, Document.tenant_id == claimed.tenant_id)) if row.document_id else None
                    if row.status == "deleted" or doc is None or doc.lifecycle_status != "active":
                        # TOMBSTONE: a customer's deletion is an explicit decision. Neither an unchanged nor a CHANGED source record reverses it (a changed content hash alone is not
                        # authorisation to recreate deleted content); the record keeps its identity so every later synchronisation finds the tombstone.
                        if row.status != "deleted":
                            row.status = "deleted"
                        s.commit()
                        return "skipped_deleted" if row.content_hash == content_hash else "tombstoned_changed"
                if row is not None and row.content_hash == content_hash:
                    row.last_synced_at, row.last_job_id = jobs._now(), job.id
                    if row_number is not None:
                        row.source_row = row_number
                    s.commit()
                    return "unchanged"
                dup = find_duplicate(s, tenant_id=claimed.tenant_id, user_id=user_id, filename=name, content_hash=content_hash)
                if dup is not None:  # identical content already exists as a document of this tenant: link, never duplicate
                    outcome, doc_id, doc_version = "linked_duplicate", uuid.UUID(dup.document_id), dup.version
                else:
                    vectors = vectors or embed_segments(embedder, kind, name, parsed.segments)  # a record that became new/changed between the pre-check and the lock
                    source_id = sources.store(s, tenant_id=claimed.tenant_id, filename=name, kind=kind, media_type=media_type, data=data, content_hash=content_hash,
                                              parse_options={"id_field": cfg.id_field})
                    result = store_parsed(s, tenant_id=claimed.tenant_id, user_id=user_id, filename=name, kind=kind, content_hash=content_hash, size_bytes=len(data),
                                          media_type=media_type, parsed=parsed, vectors=vectors, embedder=embedder, job_id=job.id, source_id=source_id)
                    outcome = "updated" if result.status == "new_version" else "created"
                    doc_id, doc_version = uuid.UUID(result.document_id), result.version
                if row is None:
                    s.add(ConnectorSyncRecord(tenant_id=claimed.tenant_id, connector_id=info.id if info.origin == "connector" else None,
                                              endpoint_id=info.id if info.origin == "endpoint" else None, source_record_id=record_id, content_hash=content_hash,
                                              source_version=version, source_row=row_number, document_id=doc_id, document_version=doc_version, last_job_id=job.id, status="active"))
                else:
                    row.content_hash, row.source_version, row.document_id, row.document_version = content_hash, version, doc_id, doc_version
                    row.last_job_id, row.last_synced_at, row.status = job.id, jobs._now(), "active"
                    row.source_row = row_number
                s.flush()
                audit.record(s, tenant_id=claimed.tenant_id, actor_type="worker", action="connector.record_ingested", entity_type="document", entity_id=doc_id,
                             details={("endpoint_id" if info.origin == "endpoint" else "connector_id"): str(info.id), "source_kind": info.kind, "source_row": row_number, "source_record_id": record_id, "outcome": outcome, "job_id": str(job.id), "sha256": content_hash,
                                      "source_version": version}, correlation_id=job.correlation_id)
                s.commit()
                return outcome
        except IntegrityError:
            continue
    raise Conflict("Concurrent synchronisation of the same record", code="sync_conflict")


def mark_documents_deleted(session, *, tenant_id, document_id) -> int:
    """Called by the document deletion (same transaction): the sync record of that document stays deleted until the source record's content changes."""
    return session.execute(update(ConnectorSyncRecord).where(ConnectorSyncRecord.tenant_id == tenant_id, ConnectorSyncRecord.document_id == document_id)
                           .values(status="deleted")).rowcount


def summary(job: IngestionJob) -> dict | None:
    """Counts only (never record content) for the API."""
    if job.job_type not in ("sync", "webhook"):
        return None
    p = job.progress or {}
    c = {**dict.fromkeys(COUNTERS, 0), **p.get("counts", {})}
    return {**c, "rejections": dict(p.get("rejections", {})), "truncated": bool(p.get("truncated"))}
