"""Webhook endpoint management (tenant administrator) and the signed delivery receiver (V41-12.01 webhook part, V41-11.01).

The receiver is the only route that is not authenticated by a bearer token: it is authenticated by an HMAC signature, and the tenant comes only from the endpoint id (see
app.ingestion.webhooks for the order of checks and the trust model). It is meant for loopback or an internal network; it is never exposed publicly by this repository."""
import os
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.ai.embeddings import get_embedder
from app.api.deps import Ctx, tenant_ctx
from app.api.v1.response_models import WebhookAccepted, WebhookEndpointOut, WebhookEndpointsList
from app.audit import service as audit
from app.core.errors import AppError, Conflict, Invalid, NotFound
from app.ingestion import webhooks
from app.ingestion.sync import parse_webhook_config
from app.models import WebhookEndpoint

webhook_endpoints_router = APIRouter(prefix="/webhook-endpoints", tags=["webhooks"])
webhooks_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SECRET_REF = r"^[A-Z][A-Z0-9_]{2,60}$"


class EndpointCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    secret_ref: str = Field(pattern=SECRET_REF)
    config: dict

    @model_validator(mode="after")
    def _config(self):
        try:
            parse_webhook_config(self.config)
        except Invalid as exc:
            raise ValueError(str(exc)) from exc
        return self


class EndpointUpdate(BaseModel):
    """Disable or re-enable an endpoint, and/or rotate its signing secret: `secret_ref` names the NEW environment variable (the old one becomes the accepted previous secret until
    `drop_previous_secret` is set)."""
    status: Literal["active", "disabled"] | None = None
    secret_ref: str | None = Field(default=None, pattern=SECRET_REF)
    drop_previous_secret: bool = False

    @model_validator(mode="after")
    def _something(self):
        if self.status is None and self.secret_ref is None and not self.drop_previous_secret:
            raise ValueError("nothing to change")
        return self


def _out(e: WebhookEndpoint) -> dict:
    return {"id": str(e.id), "name": e.name, "status": e.status, "receive_path": f"/api/v1/webhooks/{e.id}", "secret_configured": os.environ.get(e.secret_ref) is not None,
            "has_previous_secret": bool(e.previous_secret_ref), "config": e.config, "created_at": e.created_at.isoformat(), "updated_at": e.updated_at.isoformat()}


@webhook_endpoints_router.post("", status_code=201, response_model=WebhookEndpointOut, response_model_exclude_unset=True)
def create_endpoint(body: EndpointCreate, ctx: Ctx = Depends(tenant_ctx("webhooks:write"))):
    """Provision an inbound endpoint (tenant administrator). The signing secret is NOT supplied here: only the name of the server environment variable that holds it. The endpoint id in
    the returned `receive_path` is unguessable and is what binds a delivery to this tenant."""
    cfg = parse_webhook_config(body.config)
    from app.ingestion.service import DOCUMENT_KINDS
    from app.profile.service import get_profile
    profile = get_profile(ctx.session, ctx.tenant_id)
    if cfg.document_kind not in DOCUMENT_KINDS and cfg.document_kind not in (profile.allowed_kinds() if profile else set()):
        raise Invalid("The configured document kind is not allowed for this tenant", code="invalid_connector_config", status_code=422)
    endpoint = WebhookEndpoint(tenant_id=ctx.tenant_id, name=body.name, secret_ref=body.secret_ref, config=cfg.model_dump(), created_by=ctx.user_id)
    ctx.session.add(endpoint)
    try:
        ctx.session.flush()
    except Exception as exc:  # noqa: BLE001 - the unique (tenant, name) constraint
        ctx.session.rollback()
        raise Conflict("A webhook endpoint with this name already exists") from exc
    audit.record(ctx.session, tenant_id=ctx.tenant_id, actor_id=ctx.user_id, action="webhook.endpoint_created", entity_type="webhook_endpoint", entity_id=endpoint.id,
                 details={"name": body.name}, correlation_id=ctx.correlation_id)
    ctx.commit()
    ctx.session.refresh(endpoint)
    return _out(endpoint)


@webhook_endpoints_router.get("", response_model=WebhookEndpointsList, response_model_exclude_unset=True)
def list_endpoints(ctx: Ctx = Depends(tenant_ctx("webhooks:read"))):
    rows = ctx.session.scalars(select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == ctx.tenant_id).order_by(WebhookEndpoint.name)).all()
    return {"items": [_out(e) for e in rows]}


@webhook_endpoints_router.patch("/{endpoint_id}", response_model=WebhookEndpointOut, response_model_exclude_unset=True)
def update_endpoint(endpoint_id: uuid.UUID, body: EndpointUpdate, ctx: Ctx = Depends(tenant_ctx("webhooks:write"))):
    endpoint = ctx.session.scalar(select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id, WebhookEndpoint.tenant_id == ctx.tenant_id).with_for_update())
    if endpoint is None:
        raise NotFound("Webhook endpoint not found")
    changed = []
    if body.secret_ref is not None and body.secret_ref != endpoint.secret_ref:
        if body.secret_ref == endpoint.previous_secret_ref:
            raise Conflict("That secret reference is the previous one; choose a new reference", code="secret_ref_reused")
        endpoint.previous_secret_ref, endpoint.secret_ref = endpoint.secret_ref, body.secret_ref  # rotation: both stay acceptable until the previous one is dropped
        changed.append("secret_rotated")
    if body.drop_previous_secret and endpoint.previous_secret_ref:
        endpoint.previous_secret_ref = None
        changed.append("previous_secret_dropped")
    if body.status is not None and body.status != endpoint.status:
        endpoint.status = body.status
        changed.append(f"status_{body.status}")
    if changed:
        from datetime import datetime, timezone
        endpoint.updated_at = datetime.now(timezone.utc)
        audit.record(ctx.session, tenant_id=ctx.tenant_id, actor_id=ctx.user_id, action="webhook.endpoint_updated", entity_type="webhook_endpoint", entity_id=endpoint.id,
                     details={"changes": changed}, correlation_id=ctx.correlation_id)
    ctx.commit()
    ctx.session.refresh(endpoint)
    return _out(endpoint)


CONTENT_TYPE = re.compile(r"^application/json\s*(;.*)?$", re.I)


@webhooks_router.post("/{endpoint_id}", status_code=202, response_model=WebhookAccepted, response_model_exclude_unset=True,
                      openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "description": "A record object, a list of record objects, or an object holding the configured record list"}}}}})
async def receive_delivery(endpoint_id: uuid.UUID, request: Request, x_webhook_signature: str | None = Header(default=None), x_webhook_timestamp: str | None = Header(default=None),
                           x_webhook_delivery_id: str | None = Header(default=None)):
    """Signed delivery (HMAC-SHA256 over `timestamp.delivery_id.raw_body`; headers `X-Webhook-Signature: sha256=<hex>`, `X-Webhook-Timestamp` (Unix seconds) and `X-Webhook-Delivery-Id`).
    Not authenticated by a token: the endpoint id binds the tenant, the signature authenticates the sender. 202 means the delivery was durably queued (replay-protected, original stored), NOT
    that it was processed; the job (GET /ingestion/jobs) reports the outcome."""
    if not CONTENT_TYPE.match(request.headers.get("content-type", "")):
        raise AppError("Webhook deliveries must be application/json", code="unsupported_media_type", status_code=415)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > webhooks.MAX_BODY_BYTES:
        raise AppError("The delivery exceeds the size limit", code="payload_too_large", status_code=413)
    chunks, size = [], 0
    async for chunk in request.stream():  # bounded: never more than the limit is held in memory
        size += len(chunk)
        if size > webhooks.MAX_BODY_BYTES:
            raise AppError("The delivery exceeds the size limit", code="payload_too_large", status_code=413)
        chunks.append(chunk)
    body = b"".join(chunks)
    db = request.app.state.db
    correlation_id = getattr(request.state, "correlation_id", None)
    embedder = get_embedder(request.app.state.settings.embedding_backend)

    def work():
        webhooks.check_rate()
        endpoint = webhooks.lookup(db, endpoint_id)
        if endpoint is not None:
            webhooks.check_rate(endpoint_id)
        signed = webhooks.verify(endpoint, signature=x_webhook_signature, timestamp=x_webhook_timestamp, delivery_id=x_webhook_delivery_id, body=body)
        webhooks.check_timestamp(signed)
        return webhooks.accept(db, endpoint, delivery_id=x_webhook_delivery_id, body=body, embedder=embedder, correlation_id=correlation_id)

    return await run_in_threadpool(work)
