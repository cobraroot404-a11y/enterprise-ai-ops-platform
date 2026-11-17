"""Signed inbound webhooks (V41-12.01 webhook part, V41-11.01). Everything security relevant lives here so the route stays thin.

Trust model. A delivery carries no user token. The tenant is found ONLY from the unguessable endpoint id in the URL, through the narrow `webhook_endpoint_lookup` database function (migration
0013); nothing in the body or the headers ever names a tenant. The signing secret is held outside the database (the endpoint row stores an environment variable NAME) and is rotated by
naming a new variable while the previous one stays acceptable until it is dropped.

Order of checks (cheap and unauthenticated first, nothing is parsed before the signature is proven):
  1. content type, then body size (bounded streaming read: never more than MAX_BODY_BYTES in memory);
  2. a per-endpoint rate bucket (process-local; no database access for a flood of bad requests);
  3. endpoint lookup (unknown and disabled endpoints are indistinguishable from a bad signature);
  4. HMAC-SHA256 over `timestamp.delivery_id.raw_body` with the raw bytes, compared in constant time against the current and previous secret;
  5. only now the timestamp window (so the window is no oracle for anonymous callers);
  6. the payload (JSON, shape, record count) is validated;
  7. ONE transaction: the replay ledger insert (UNIQUE endpoint+delivery id decides atomically), the raw body as a retained original, the durable job, the audit event; 202 only after it commits.
Signature failures are counted and logged but NOT written to the audit log: an unauthenticated caller must not be able to flood a tenant's audit trail. Deliveries that passed authentication
(accepted, replayed, payload-rejected) are audited, without content. A 202 means "durably queued", never "processed": the worker processes the delivery through the same per-record pipeline as
REST and CSV (idempotency, provenance, tombstones, retained originals)."""
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.connectors.http import resolve_secret
from app.connectors.ratelimit import LIMITERS, RateLimited
from app.core.errors import AppError, Invalid
from app.database.session import Database
from app.ingestion import jobs, sources
from app.ingestion.sync import _blank_progress, parse_webhook_config, webhook_records
from app.models import WebhookDelivery
from app.observability.logging import log_event
from app.observability.metrics import METRICS

log = logging.getLogger("eaop.webhook")

MAX_BODY_BYTES = 256 * 1024
TOLERANCE_SECONDS = 300  # a delivery whose signed timestamp is further than this from the server clock is rejected
DELIVERY_ID = re.compile(r"^[A-Za-z0-9._:\-]{8,64}$")
SIGNATURE = re.compile(r"^sha256=([0-9a-f]{64})$")
RATE_PER_SECOND, RATE_BURST = 20.0, 40  # per endpoint, process-local (not distributed)


class WebhookAuthError(AppError):
    """Authentication of a delivery failed. One fixed body for every cause that an anonymous caller could probe (unknown, disabled, bad signature)."""
    status_code = 401
    code = "invalid_signature"

    def __init__(self):
        super().__init__("The webhook signature could not be verified")


@dataclass
class Endpoint:
    id: str
    tenant_id: str
    name: str
    secret_ref: str
    previous_secret_ref: str | None
    status: str
    config: dict


def sign(secret: str, timestamp: int | str, delivery_id: str, body: bytes) -> str:
    """The signature a sender must send: `sha256=` plus HMAC-SHA256 hex over `<timestamp>.<delivery id>.` followed by the raw body bytes."""
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.{delivery_id}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def lookup(db: Database, endpoint_id) -> Endpoint | None:
    with db.session() as s:  # no tenant context exists yet: the function is the only way to resolve it
        row = s.execute(text("SELECT tenant_id, secret_ref, previous_secret_ref, status, config, name FROM webhook_endpoint_lookup(CAST(:i AS uuid))"), {"i": str(endpoint_id)}).first()
    if row is None:
        return None
    return Endpoint(str(endpoint_id), str(row[0]), row[5], row[1], row[2], row[3], dict(row[4] or {}))


ANONYMOUS_PER_SECOND, ANONYMOUS_BURST = 200.0, 400  # all receiver traffic before an endpoint is resolved (bounds database lookups for a flood of unknown ids)


def check_rate(endpoint_id=None) -> None:
    """Without an endpoint: the shared pre-lookup bucket. With a resolved endpoint: that endpoint's own bucket (buckets exist only for real endpoints, so the registry stays bounded)."""
    try:
        if endpoint_id is None:
            LIMITERS.get("webhook", "anonymous", ANONYMOUS_PER_SECOND, ANONYMOUS_BURST).acquire(0)
        else:
            LIMITERS.get("webhook", endpoint_id, RATE_PER_SECOND, RATE_BURST).acquire(0)
    except RateLimited as exc:
        METRICS.incr("webhook_deliveries_total", outcome="rate_limited")
        wait = max(1, int(-(-exc.retry_after // 1))) if exc.retry_after else 1
        raise AppError("Too many deliveries for this endpoint; retry shortly", code="webhook_rate_limited", status_code=429, retry_after=wait) from exc


def verify(endpoint: Endpoint | None, *, signature: str | None, timestamp: str | None, delivery_id: str | None, body: bytes) -> int:
    """Raise WebhookAuthError unless the signature is valid for the current or previous secret; return the signed timestamp. Constant-time comparison."""
    if endpoint is None or endpoint.status != "active" or not signature or not timestamp or not delivery_id:
        _reject("unknown_or_incomplete")
    m = SIGNATURE.match(signature or "")
    if not m or not DELIVERY_ID.match(delivery_id or "") or not (timestamp or "").isdigit() or len(timestamp) > 12:
        _reject("malformed")
    secrets = [resolve_secret(endpoint.secret_ref)]
    if endpoint.previous_secret_ref:
        secrets.append(resolve_secret(endpoint.previous_secret_ref))
    if not secrets[0]:
        METRICS.incr("webhook_deliveries_total", outcome="not_configured")
        raise AppError("The webhook endpoint is not configured on the server", code="webhook_not_configured", status_code=503, retry_after=30)
    ok = False
    for secret in (x for x in secrets if x):  # every candidate is compared (no early exit that reveals which secret matched)
        ok = hmac.compare_digest(sign(secret, timestamp, delivery_id, body)[7:], m.group(1)) or ok
    if not ok:
        _reject("bad_signature")
    return int(timestamp)


def _reject(reason: str):
    METRICS.incr("webhook_deliveries_total", outcome="rejected_" + reason)
    log_event(log, "webhook.rejected", level=logging.WARNING, reason=reason)
    raise WebhookAuthError()


def check_timestamp(signed: int, now: float | None = None) -> None:
    if abs((now if now is not None else time.time()) - signed) > TOLERANCE_SECONDS:
        METRICS.incr("webhook_deliveries_total", outcome="rejected_timestamp")
        raise AppError("The delivery timestamp is outside the accepted window", code="timestamp_out_of_window", status_code=401)


def accept(db: Database, endpoint: Endpoint, *, delivery_id: str, body: bytes, embedder, correlation_id: str | None) -> dict:
    """Steps 6 and 7. Raises AppError (422 invalid_payload, 409 webhook_replayed); returns the accepted delivery. The delivery id is consumed even by a payload-rejected delivery."""
    cfg = parse_webhook_config(endpoint.config)
    body_hash = hashlib.sha256(body).hexdigest()
    problem = None
    try:
        webhook_records(json.loads(body), cfg)
    except (ValueError, UnicodeDecodeError):
        problem = Invalid("The payload is not valid JSON", code="invalid_payload", status_code=422)
    except Invalid as exc:
        problem = exc
    try:
        with db.session(tenant_id=endpoint.tenant_id) as s:
            job_id = None if problem else uuid.uuid4()  # chosen up front: the ledger row is append-only, so it is written once with its job id
            delivery = WebhookDelivery(tenant_id=endpoint.tenant_id, endpoint_id=endpoint.id, delivery_id=delivery_id, body_sha256=body_hash,
                                       outcome="rejected_invalid_payload" if problem else "accepted", job_id=job_id)
            s.add(delivery)
            s.flush()  # the UNIQUE (endpoint, delivery id) insert decides atomically: concurrent identical deliveries produce exactly one winner
            if problem:
                audit.record(s, tenant_id=endpoint.tenant_id, actor_type="webhook", action="webhook.delivery_rejected", entity_type="webhook_endpoint", entity_id=endpoint.id,
                             details={"delivery_id": delivery_id, "reason": problem.code, "sha256": body_hash}, correlation_id=correlation_id)
                s.commit()
                METRICS.incr("webhook_deliveries_total", outcome="rejected_payload")
                raise problem
            source_id = sources.store(s, tenant_id=endpoint.tenant_id, filename=f"webhook-{endpoint.name}"[:100] + ".json", kind=cfg.document_kind, media_type="application/json",
                                      data=body, content_hash=body_hash)
            job = jobs.new_job(s, tenant_id=endpoint.tenant_id, job_type="webhook", requested_by=None, correlation_id=correlation_id, filename=endpoint.name, kind=cfg.document_kind,
                               idempotency_key=f"webhook:{endpoint.id}:{delivery_id}", config=jobs.processing_config(embedder), source_id=source_id, endpoint_id=endpoint.id,
                               progress=_blank_progress(), job_id=job_id)
            audit.record(s, tenant_id=endpoint.tenant_id, actor_type="webhook", action="webhook.delivery_accepted", entity_type="webhook_endpoint", entity_id=endpoint.id,
                         details={"delivery_id": delivery_id, "job_id": str(job.id), "sha256": body_hash, "bytes": len(body)}, correlation_id=correlation_id)
            s.commit()
            METRICS.incr("webhook_deliveries_total", outcome="accepted")
            return {"delivery_id": delivery_id, "job_id": str(job.id), "status": "QUEUED"}
    except IntegrityError as exc:
        _audit_replay(db, endpoint, delivery_id, body_hash, correlation_id)
        METRICS.incr("webhook_deliveries_total", outcome="replayed")
        raise AppError("This delivery id was already received for this endpoint", code="webhook_replayed", status_code=409) from exc


def _audit_replay(db: Database, endpoint: Endpoint, delivery_id: str, body_hash: str, correlation_id) -> None:
    with db.session(tenant_id=endpoint.tenant_id) as s:  # authenticated delivery: a replay is a security-relevant, auditable outcome
        audit.record(s, tenant_id=endpoint.tenant_id, actor_type="webhook", action="webhook.delivery_replayed", entity_type="webhook_endpoint", entity_id=endpoint.id,
                     details={"delivery_id": delivery_id, "sha256": body_hash}, correlation_id=correlation_id)
        s.commit()
