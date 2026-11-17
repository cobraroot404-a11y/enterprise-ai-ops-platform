"""Documents, search, AI, incidents, tickets, approvals, workflows, audit, metrics."""
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from app.ai.embeddings import get_embedder
from app.ai.llm import get_llm
from app.ai.rag import answer_question
from app.api.deps import Ctx, tenant_ctx
from app.api.v1.response_models import (
    ApprovalDecisionOut,
    AskResponse,
    AuditEventItem,
    DocumentDeletion,
    DocumentDetail,
    DocumentRow,
    DocumentUploaded,
    IncidentOut,
    IngestionJobOut,
    IngestionStatus,
    Metrics,
    Page,
    SearchResponse,
    TicketOut,
    WorkflowEvent,
)
from app.core.errors import Invalid, NotFound
from app.core.request_limits import enforce_tenant_rate
from app.ingestion import jobs as ingestion_jobs
from app.ingestion.lifecycle import delete_document, mask_deleted_sources
from app.ingestion.parsers import extension_of, safe_filename
from app.ingestion.service import DOCUMENT_KINDS
from app.models import (
    Approval,
    AuditEvent,
    Document,
    DocumentVersion,
    Incident,
    IngestionJob,
    OutboxEvent,
    Ticket,
    User,
)
from app.observability.metrics import METRICS
from app.profile.service import get_profile
from app.retrieval.search import search
from app.schemas.incident import ExtractRequest, MeasurementVerification
from app.services.incident_service import asset_in_register, extract_incident, register_kind_for
from app.workflows import ticket_service as tickets

documents_router = APIRouter(prefix="/documents", tags=["documents"])
search_router = APIRouter(prefix="/search", tags=["search"])
ai_router = APIRouter(prefix="/ai", tags=["ai"])
incidents_router = APIRouter(prefix="/incidents", tags=["incidents"])
tickets_router = APIRouter(prefix="/tickets", tags=["tickets"])
approvals_router = APIRouter(prefix="/approvals", tags=["approvals"])
workflows_router = APIRouter(prefix="/workflows", tags=["workflows"])
audit_router = APIRouter(prefix="/audit", tags=["audit"])
metrics_router = APIRouter(prefix="/metrics", tags=["metrics"])
ingestion_router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _providers(request: Request):
    settings = request.app.state.settings
    return get_embedder(settings.embedding_backend), get_llm(settings.llm_backend)


def _page(limit: int, offset: int):
    return limit, offset


Limit = Query(50, ge=1, le=100)
Offset = Query(0, ge=0)
ESC = "\\"  # LIKE escape character


def _like(term: str) -> str:
    """Escape LIKE wildcards in user input so a search term is matched literally."""
    return "%" + term.replace(ESC, ESC + ESC).replace("%", ESC + "%").replace("_", ESC + "_") + "%"


def _ordered(query, sort: str | None, order: str, allowed: dict, default):
    column = allowed.get(sort or "", default)
    return query.order_by(column.asc() if order == "asc" else column.desc())


def ticket_out(t: Ticket) -> dict:
    return {"id": str(t.id), "incident_id": str(t.incident_id), "title": t.title, "description": t.description,
            "priority": t.priority, "state": t.state, "external_ticket_id": t.external_ticket_id,
            "attempts": t.attempts, "last_error": t.last_error, "created_by": str(t.created_by),
            "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
            "submitted_at": t.submitted_at.isoformat() if t.submitted_at else None}


def incident_out(i: Incident) -> dict:
    return mask_deleted_sources(i, _incident_dict(i))


def _incident_dict(i: Incident) -> dict:
    return {"id": str(i.id), "asset_id": i.asset_id, "asset_verified": i.asset_verified, "category": i.category,
            "symptoms": i.symptoms, "related_incidents": i.related_incidents, "priority": i.priority,
            "citations": i.citations, "recommended_action": i.recommended_action,
            "review_status": i.review_status, "notes": i.notes, "measurements": i.measurements or [],
            "review_urgency": ("urgent" if any(m.get("potentially_critical") for m in (i.measurements or [])) else "routine" if i.review_status == "needs_review" else "none"),
            "report_text": i.report_text,
            "extraction_backend": i.extraction_backend, "created_at": i.created_at.isoformat()}


# ---- documents / ingestion ------------------------------------------------------------------------
@documents_router.post("", status_code=201, response_model=DocumentUploaded, response_model_exclude_unset=True)
async def upload_document(request: Request, file: UploadFile = File(...), kind: str = Form("other"),
                          ctx: Ctx = Depends(tenant_ctx("documents:write"))):
    settings = request.app.state.settings
    filename = safe_filename(file.filename or "")
    extension_of(filename)  # reject disallowed types before reading the body
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise Invalid("File too large", code="file_too_large", status_code=413)
    profile = get_profile(ctx.session, ctx.tenant_id)  # tenant-specific kinds and CSV/JSON mappings (config)
    extra_kinds = profile.allowed_kinds() if profile else set()
    if kind not in DOCUMENT_KINDS and kind not in extra_kinds:
        raise Invalid(f"kind must be one of {sorted(DOCUMENT_KINDS | extra_kinds)}", code="invalid_kind")
    mapping = profile.field_maps.get(kind) if profile else None
    embedder, _ = _providers(request)
    enforce_tenant_rate(request, ctx.tenant_id, "upload")

    def work():  # CPU-heavy (parsing, embedding): bounded, and kept off the event loop
        timer = METRICS.timer("ingestion_seconds", tenant=str(ctx.tenant_id))
        with request.app.state.limiters["ingestion"].slot(ctx.tenant_id), timer:
            # Same synchronous contract as before; every attempt is now a durable, audited ingestion job (retry and status: see /ingestion/jobs).
            result = ingestion_jobs.run_upload(request.app.state.db, ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, filename=filename,
                                               data=data, kind=kind, embedder=embedder, correlation_id=ctx.correlation_id,
                                               extra_kinds=extra_kinds, field_map=mapping.columns if mapping else None,
                                               id_field=mapping.id_field if mapping else None)
            ctx.commit()
            return result

    return (await run_in_threadpool(work)).__dict__


@documents_router.get("", response_model=Page[DocumentRow], response_model_exclude_unset=True)
def list_documents(limit: int = Limit, offset: int = Offset, kind: str | None = None,
                   q: str | None = Query(None, max_length=100), sort: str | None = None,
                   order: str = Query("desc", pattern="^(asc|desc)$"),
                   ctx: Ctx = Depends(tenant_ctx("documents:read"))):
    query = select(Document).where(Document.tenant_id == ctx.tenant_id, Document.lifecycle_status == "active")
    if kind:
        query = query.where(Document.kind == kind)
    if q:
        query = query.where(Document.filename.ilike(_like(q), escape=ESC))
    total = ctx.session.scalar(select(func.count()).select_from(query.subquery()))
    query = _ordered(query, sort, order, {"filename": Document.filename, "kind": Document.kind,
                                          "created_at": Document.created_at}, Document.created_at)
    rows = ctx.session.scalars(query.limit(limit).offset(offset)).all()
    versions = {v.document_id: v for v in ctx.session.scalars(
        select(DocumentVersion).where(DocumentVersion.tenant_id == ctx.tenant_id))
        if v.version == next((d.current_version for d in rows if d.id == v.document_id), -1)}
    return {"total": total, "limit": limit, "offset": offset, "items": [
        {"id": str(d.id), "filename": d.filename, "kind": d.kind, "current_version": d.current_version,
         "chunk_count": versions[d.id].chunk_count if d.id in versions else None,
         "page_count": versions[d.id].page_count if d.id in versions else None,
         "created_at": d.created_at.isoformat()} for d in rows]}


@documents_router.get("/{document_id}", response_model=DocumentDetail, response_model_exclude_unset=True)
def get_document(document_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("documents:read"))):
    doc = ctx.session.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == ctx.tenant_id,
                                                    Document.lifecycle_status == "active"))
    if doc is None:  # unknown, another tenant's, and deleted documents are indistinguishable
        raise NotFound("Document not found")
    versions = ctx.session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                                   .order_by(DocumentVersion.version)).all()
    return {"id": str(doc.id), "filename": doc.filename, "kind": doc.kind, "current_version": doc.current_version,
            "versions": [{"version": v.version, "sha256": v.content_hash, "chunks": v.chunk_count,
                          "size_bytes": v.size_bytes, "embedding_backend": v.embedding_backend,
                          "created_at": v.created_at.isoformat()} for v in versions]}


@documents_router.post("/{document_id}/reprocess", status_code=202, response_model=IngestionJobOut, response_model_exclude_unset=True)
def reprocess_document(document_id: uuid.UUID, request: Request, ctx: Ctx = Depends(tenant_ctx("documents:reprocess"))):
    """Queue an explicit reprocessing of an active document (tenant administrator or supervisor). The worker re-derives the current version's chunks as a replacement generation,
    validates it, then activates it; until then (and if it fails) the previously active content keeps serving. Repeating the request returns the active job."""
    embedder, _ = _providers(request)
    job = ingestion_jobs.request_reprocess(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, document_id=document_id, embedder=embedder,
                                           correlation_id=ctx.correlation_id)
    ctx.commit()
    return ingestion_jobs.job_out(job)


@documents_router.delete("/{document_id}", response_model=DocumentDeletion, response_model_exclude_unset=True)
def delete_document_route(document_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("documents:delete"))):
    """Audited deletion. Stage A (this request): the document is logically deleted at once (excluded from listings, search, retrieval, citations and direct access) and its
    content cleanup is queued for the worker. Repeating the request returns the current state (and re-queues a cleanup that failed). Another tenant's id is a 404."""
    state = delete_document(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, document_id=document_id, correlation_id=ctx.correlation_id)
    ctx.commit()
    return state.to_dict()


@ingestion_router.get("/jobs", response_model=Page[IngestionJobOut], response_model_exclude_unset=True)
def list_ingestion_jobs(limit: int = Limit, offset: int = Offset, status: str | None = Query(None, pattern="^(QUEUED|PROCESSING|RETRY_PENDING|COMPLETED|FAILED|CANCELLED)$"),
                        job_type: str | None = Query(None, pattern="^(ingest|reprocess|sync|webhook)$"), document_id: uuid.UUID | None = None,
                        ctx: Ctx = Depends(tenant_ctx("documents:read"))):
    query = select(IngestionJob).where(IngestionJob.tenant_id == ctx.tenant_id)
    if status:
        query = query.where(IngestionJob.status == status)
    if job_type:
        query = query.where(IngestionJob.job_type == job_type)
    if document_id:
        query = query.where(IngestionJob.document_id == document_id)
    total = ctx.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = ctx.session.scalars(query.order_by(IngestionJob.created_at.desc(), IngestionJob.id).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [ingestion_jobs.job_out(j) for j in rows]}


@ingestion_router.get("/jobs/{job_id}", response_model=IngestionJobOut, response_model_exclude_unset=True)
def get_ingestion_job(job_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("documents:read"))):
    job = ctx.session.scalar(select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.tenant_id == ctx.tenant_id))
    if job is None:  # unknown and another tenant's job are indistinguishable
        raise NotFound("Ingestion job not found")
    return ingestion_jobs.job_out(job)


@ingestion_router.post("/jobs/{job_id}/retry", status_code=202, response_model=IngestionJobOut, response_model_exclude_unset=True)
def retry_ingestion_job(job_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("documents:reprocess"))):
    """Authorised manual retry of a FAILED reprocessing job (a failed upload keeps no content and must be uploaded again). 409 for any other state."""
    job = ingestion_jobs.request_retry(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, job_id=job_id, correlation_id=ctx.correlation_id)
    ctx.commit()
    return ingestion_jobs.job_out(job)


@ingestion_router.get("/status", response_model=IngestionStatus, response_model_exclude_unset=True)
def ingestion_status(ctx: Ctx = Depends(tenant_ctx("documents:read"))):
    row = ctx.session.execute(text(
        "SELECT count(*) AS docs, coalesce(sum(v.chunk_count),0) AS chunks FROM document_versions v JOIN documents d ON d.id = v.document_id "
        "WHERE v.tenant_id = :t AND d.lifecycle_status = 'active'"), {"t": str(ctx.tenant_id)}).one()
    return {"documents_versions": row.docs, "chunks": int(row.chunks)}


# ---- search / AI ----------------------------------------------------------------------------------
class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(5, ge=1, le=20)
    kinds: list[str] | None = None


@search_router.post("", response_model=SearchResponse, response_model_exclude_unset=True)
def search_endpoint(body: SearchRequest, request: Request, ctx: Ctx = Depends(tenant_ctx("search:read"))):
    embedder, _ = _providers(request)
    hits = search(ctx.session, ctx.tenant_id, body.query, embedder, k=body.k, kinds=body.kinds)
    return {"embedding_backend": embedder.name, "items": [h.to_dict() for h in hits]}


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@ai_router.post("/ask", response_model=AskResponse, response_model_exclude_unset=True)
def ask(body: AskRequest, request: Request, ctx: Ctx = Depends(tenant_ctx("search:read"))):
    embedder, llm = _providers(request)
    enforce_tenant_rate(request, ctx.tenant_id, "ask")
    with request.app.state.limiters["inference"].slot(ctx.tenant_id):
        result = answer_question(ctx.session, ctx.tenant_id, body.question, embedder, llm)
    from app.audit import service as audit
    audit.record(ctx.session, tenant_id=ctx.tenant_id, actor_id=ctx.user_id, action="ai.ask",
                 entity_type="query", details={"grounded": result.grounded,
                                               "insufficient_evidence": result.insufficient_evidence,
                                               "citations": len(result.citations),
                                               "llm_backend": result.llm_backend},
                 correlation_id=ctx.correlation_id)
    ctx.commit()
    return result.__dict__


# ---- incidents ------------------------------------------------------------------------------------
@incidents_router.post("/extract", status_code=201, response_model=IncidentOut, response_model_exclude_unset=True)
def extract(body: ExtractRequest, request: Request, ctx: Ctx = Depends(tenant_ctx("incidents:write"))):
    embedder, llm = _providers(request)
    enforce_tenant_rate(request, ctx.tenant_id, "extract")
    with request.app.state.limiters["inference"].slot(ctx.tenant_id):
        incident = extract_incident(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
                                    report_text=body.report_text, embedder=embedder, llm=llm,
                                    correlation_id=ctx.correlation_id, structured_observations=[o.model_dump() for o in body.observations],
                                    numeric_locale=body.numeric_locale)
    ctx.commit()
    return incident_out(incident)


@incidents_router.get("", response_model=Page[IncidentOut], response_model_exclude_unset=True)
def list_incidents(limit: int = Limit, offset: int = Offset, asset_id: str | None = None,
                   review_status: str | None = Query(None, pattern="^(pending_review|needs_review|accepted|rejected)$"),
                   priority: str | None = Query(None, pattern="^P[1-4]$"), q: str | None = Query(None, max_length=100),
                   sort: str | None = None, order: str = Query("desc", pattern="^(asc|desc)$"),
                   ctx: Ctx = Depends(tenant_ctx("incidents:read"))):
    query = select(Incident).where(Incident.tenant_id == ctx.tenant_id)
    if asset_id:
        query = query.where(Incident.asset_id == asset_id)
    if review_status:
        query = query.where(Incident.review_status == review_status)
    if priority:
        query = query.where(Incident.priority == priority)
    if q:
        pattern = _like(q)
        query = query.where(Incident.asset_id.ilike(pattern, escape=ESC) | Incident.category.ilike(pattern, escape=ESC)
                            | Incident.report_text.ilike(pattern, escape=ESC))
    total = ctx.session.scalar(select(func.count()).select_from(query.subquery()))
    query = _ordered(query, sort, order, {"created_at": Incident.created_at, "priority": Incident.priority,
                                          "asset_id": Incident.asset_id, "review_status": Incident.review_status},
                     Incident.created_at)
    rows = ctx.session.scalars(query.limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [incident_out(i) for i in rows]}


@incidents_router.get("/{incident_id}", response_model=IncidentOut, response_model_exclude_unset=True)
def get_incident(incident_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("incidents:read"))):
    incident = ctx.session.scalar(select(Incident).where(Incident.id == incident_id,
                                                         Incident.tenant_id == ctx.tenant_id))
    if incident is None:
        raise NotFound("Incident not found")
    return incident_out(incident)


class IncidentReview(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")
    comment: str = Field(min_length=5, max_length=1000)


@incidents_router.post("/{incident_id}/review", response_model=IncidentOut, response_model_exclude_unset=True)
def review_incident(incident_id: uuid.UUID, body: IncidentReview,
                    ctx: Ctx = Depends(tenant_ctx("incidents:review"))):
    """Human review of an incident flagged needs_review (unverified equipment or no evidence)."""
    from app.audit import service as audit
    incident = ctx.session.scalar(select(Incident).where(Incident.id == incident_id,
                                                         Incident.tenant_id == ctx.tenant_id).with_for_update())
    if incident is None:
        raise NotFound("Incident not found")
    if incident.review_status != "needs_review":
        raise Invalid(f"Only incidents in needs_review can be reviewed (status is {incident.review_status})",
                      code="not_reviewable", status_code=409)
    previous = incident.review_status
    incident.review_status = "accepted" if body.decision == "accept" else "rejected"
    METRICS.incr("incident_reviews_total", tenant=str(ctx.tenant_id), decision=body.decision)
    # The human decision is recorded as a separate, labelled note. It never alters asset_verified or the
    # citations: unsupported AI claims stay unverified, and the ticket still needs its own approval.
    verb = "accepted" if body.decision == "accept" else "rejected"
    incident.notes = [*incident.notes, f"Human review: {verb} by a supervisor. Justification: {body.comment}"]
    audit.record(ctx.session, tenant_id=ctx.tenant_id, actor_id=ctx.user_id, action=f"incident.review_{body.decision}",
                 entity_type="incident", entity_id=incident.id,
                 details={"from": previous, "comment": body.comment}, correlation_id=ctx.correlation_id)
    ctx.commit()
    return incident_out(incident)


@incidents_router.post("/{incident_id}/measurements/{name}/verify", response_model=IncidentOut, response_model_exclude_unset=True)
def verify_measurement_route(incident_id: uuid.UUID, name: str, body: MeasurementVerification, ctx: Ctx = Depends(tenant_ctx("incidents:review"))):
    """Human verification of a candidate measurement (supervisor/admin, never the incident's creator). The only path from a candidate to numeric priority besides signed simulation data."""
    from app.services.incident_service import verify_measurement
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name):
        raise Invalid("Invalid measurement name", code="invalid_measurement_name")
    incident = verify_measurement(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, incident_id=incident_id, name=name, decision=body.decision,
                                  comment=body.comment, expected_trust_status=body.expected_trust_status, correlation_id=ctx.correlation_id)
    ctx.commit()
    return incident_out(incident)


@incidents_router.post("/{incident_id}/verify-asset", response_model=IncidentOut, response_model_exclude_unset=True)
def verify_asset(incident_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("incidents:review"))):
    """Re-check the incident's equipment against the tenant's authoritative register.

    This is the only way asset_verified can become true after extraction. It is set from the register
    (populated through audited document ingestion), never from a reviewer's say-so.
    """
    from app.audit import service as audit
    incident = ctx.session.scalar(select(Incident).where(Incident.id == incident_id,
                                                         Incident.tenant_id == ctx.tenant_id).with_for_update())
    if incident is None:
        raise NotFound("Incident not found")
    if incident.review_status == "rejected":
        raise Invalid("Rejected incidents cannot be re-verified", code="not_reviewable", status_code=409)
    found = asset_in_register(ctx.session, ctx.tenant_id, incident.asset_id,
                              register_kind_for(ctx.session, ctx.tenant_id))
    if found and not incident.asset_verified:
        incident.asset_verified = True
        incident.notes = [*incident.notes, f"Equipment {incident.asset_id} later verified against the register."]
    audit.record(ctx.session, tenant_id=ctx.tenant_id, actor_id=ctx.user_id, action="incident.asset_reverified",
                 entity_type="incident", entity_id=incident.id,
                 details={"asset_id": incident.asset_id, "found_in_register": found},
                 correlation_id=ctx.correlation_id)
    ctx.commit()
    return incident_out(incident)


# ---- tickets --------------------------------------------------------------------------------------
class TicketCreate(BaseModel):
    incident_id: uuid.UUID


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=3, max_length=8000)
    priority: str | None = Field(default=None, pattern="^P[1-4]$")


@tickets_router.post("", status_code=201, response_model=TicketOut, response_model_exclude_unset=True)
def create_ticket(body: TicketCreate, ctx: Ctx = Depends(tenant_ctx("tickets:write"))):
    ticket = tickets.create_draft(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
                                  incident_id=body.incident_id, correlation_id=ctx.correlation_id)
    ctx.commit()
    return ticket_out(ticket)


@tickets_router.get("", response_model=Page[TicketOut], response_model_exclude_unset=True)
def list_tickets(limit: int = Limit, offset: int = Offset, state: str | None = None,
                 priority: str | None = Query(None, pattern="^P[1-4]$"), q: str | None = Query(None, max_length=100),
                 sort: str | None = None, order: str = Query("desc", pattern="^(asc|desc)$"),
                 ctx: Ctx = Depends(tenant_ctx("tickets:read"))):
    query = select(Ticket).where(Ticket.tenant_id == ctx.tenant_id)
    if state:
        query = query.where(Ticket.state == state)
    if priority:
        query = query.where(Ticket.priority == priority)
    if q:
        pattern = _like(q)
        query = query.where(Ticket.title.ilike(pattern, escape=ESC)
                            | Ticket.external_ticket_id.ilike(pattern, escape=ESC))
    total = ctx.session.scalar(select(func.count()).select_from(query.subquery()))
    query = _ordered(query, sort, order, {"created_at": Ticket.created_at, "priority": Ticket.priority,
                                          "state": Ticket.state, "updated_at": Ticket.updated_at}, Ticket.created_at)
    rows = ctx.session.scalars(query.limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [ticket_out(t) for t in rows]}


@tickets_router.get("/{ticket_id}", response_model=TicketOut, response_model_exclude_unset=True)
def get_ticket(ticket_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("tickets:read"))):
    return ticket_out(tickets.get_ticket(ctx.session, ctx.tenant_id, ticket_id))


@tickets_router.patch("/{ticket_id}", response_model=TicketOut, response_model_exclude_unset=True)
def edit_ticket(ticket_id: uuid.UUID, body: TicketUpdate, ctx: Ctx = Depends(tenant_ctx("tickets:write"))):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise Invalid("No changes supplied")
    ticket = tickets.update_draft(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
                                  ticket_id=ticket_id, changes=changes, correlation_id=ctx.correlation_id)
    ctx.commit()
    return ticket_out(ticket)


@tickets_router.post("/{ticket_id}/request-approval", response_model=TicketOut, response_model_exclude_unset=True)
def request_approval(ticket_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("tickets:write"))):
    ticket = tickets.request_approval(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id,
                                      ticket_id=ticket_id, correlation_id=ctx.correlation_id)
    ctx.commit()
    return ticket_out(ticket)


@tickets_router.post("/{ticket_id}/cancel", response_model=TicketOut, response_model_exclude_unset=True)
def cancel_ticket(ticket_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("tickets:write"))):
    ticket = tickets.cancel(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id,
                            correlation_id=ctx.correlation_id)
    ctx.commit()
    return ticket_out(ticket)


@tickets_router.post("/{ticket_id}/submit", response_model=TicketOut, response_model_exclude_unset=True)
def submit_ticket(ticket_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("tickets:write"))):
    ticket = tickets.submit(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id,
                            correlation_id=ctx.correlation_id)
    ctx.commit()
    return ticket_out(ticket)


@tickets_router.post("/{ticket_id}/retry", response_model=TicketOut, response_model_exclude_unset=True)
def retry_ticket(ticket_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("tickets:retry"))):
    ticket = tickets.retry(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id,
                           correlation_id=ctx.correlation_id)
    ctx.commit()
    return ticket_out(ticket)


# ---- approvals ------------------------------------------------------------------------------------
class Decision(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    comment: str | None = Field(default=None, max_length=1000)


@approvals_router.get("", response_model=Page[TicketOut] | Page[ApprovalDecisionOut], response_model_exclude_unset=True)
def approval_queue(limit: int = Limit, offset: int = Offset, status: str = "pending",
                   ctx: Ctx = Depends(tenant_ctx("approvals:read"))):
    if status == "pending":
        q = select(Ticket).where(Ticket.tenant_id == ctx.tenant_id, Ticket.state == "PENDING_APPROVAL")
        total = ctx.session.scalar(select(func.count()).select_from(q.subquery()))
        rows = ctx.session.scalars(q.order_by(Ticket.updated_at).limit(limit).offset(offset)).all()
        return {"total": total, "limit": limit, "offset": offset, "items": [ticket_out(t) for t in rows]}
    q = select(Approval).where(Approval.tenant_id == ctx.tenant_id)
    total = ctx.session.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.session.scalars(q.order_by(Approval.decided_at.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [
        {"ticket_id": str(a.ticket_id), "decision": a.decision, "decided_by": str(a.decided_by),
         "comment": a.comment, "decided_at": a.decided_at.isoformat()} for a in rows]}


@approvals_router.post("/{ticket_id}/decision", response_model=TicketOut, response_model_exclude_unset=True)
def decide(ticket_id: uuid.UUID, body: Decision, ctx: Ctx = Depends(tenant_ctx("approvals:decide"))):
    ticket = tickets.decide(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, ticket_id=ticket_id,
                            decision=body.decision, comment=body.comment, correlation_id=ctx.correlation_id)
    ctx.commit()
    return ticket_out(ticket)


# ---- workflows / audit / metrics --------------------------------------------------------------------
@workflows_router.get("", response_model=Page[WorkflowEvent], response_model_exclude_unset=True)
def workflow_history(limit: int = Limit, offset: int = Offset,
                     status: str | None = Query(None, pattern="^(pending|processing|done|dead)$"),
                     ticket_id: uuid.UUID | None = None, ctx: Ctx = Depends(tenant_ctx("workflows:read"))):
    q = select(OutboxEvent).where(OutboxEvent.tenant_id == ctx.tenant_id)
    if status:
        q = q.where(OutboxEvent.status == status)
    if ticket_id:
        q = q.where(OutboxEvent.aggregate_id == ticket_id)
    total = ctx.session.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.session.scalars(q.order_by(OutboxEvent.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [
        {"id": e.id, "topic": e.topic, "ticket_id": str(e.aggregate_id), "status": e.status,
         "attempts": e.attempts, "last_error": e.last_error, "created_at": e.created_at.isoformat(),
         "processed_at": e.processed_at.isoformat() if e.processed_at else None} for e in rows]}


@audit_router.get("", response_model=Page[AuditEventItem], response_model_exclude_unset=True)
def audit_log(limit: int = Limit, offset: int = Offset, entity_id: str | None = None,
              action: str | None = None, entity_type: str | None = Query(None, max_length=40),
              q_text: str | None = Query(None, alias="q", max_length=100),
              ctx: Ctx = Depends(tenant_ctx("audit:read"))):
    q = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if q_text:
        q = q.where(AuditEvent.action.ilike(_like(q_text), escape=ESC))
    if entity_id:
        q = q.where(AuditEvent.entity_id == entity_id)
    if action:
        q = q.where(AuditEvent.action == action)
    total = ctx.session.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.session.scalars(q.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)).all()
    names = {u.id: u.email for u in ctx.session.scalars(select(User).where(
        User.id.in_([r.actor_id for r in rows if r.actor_id])))} if rows else {}
    return {"total": total, "limit": limit, "offset": offset, "items": [
        {"id": r.id, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id,
         "actor": names.get(r.actor_id) or r.actor_type, "actor_type": r.actor_type, "details": r.details,
         "correlation_id": r.correlation_id, "created_at": r.created_at.isoformat()} for r in rows]}


@metrics_router.get("", response_model=Metrics, response_model_exclude_unset=True)
def metrics(ctx: Ctx = Depends(tenant_ctx("metrics:read"))):
    """Real counts computed from this tenant's data; nothing is estimated."""
    by_state = dict(ctx.session.execute(text(
        "SELECT state, count(*) FROM tickets WHERE tenant_id = :t GROUP BY state"),
        {"t": str(ctx.tenant_id)}).all())
    turnaround = ctx.session.execute(text(
        "SELECT count(*) AS n, avg(extract(epoch FROM decided_at - requested_at)) AS avg_s "
        "FROM approvals WHERE tenant_id = :t AND requested_at IS NOT NULL"), {"t": str(ctx.tenant_id)}).one()
    counts = ctx.session.execute(text(
        "SELECT (SELECT count(*) FROM documents WHERE tenant_id = :t AND lifecycle_status = 'active') AS documents, "
        "(SELECT count(*) FROM incidents WHERE tenant_id = :t) AS incidents, "
        "(SELECT count(*) FROM outbox_events WHERE tenant_id = :t AND status = 'dead') AS dead_letters, "
        "(SELECT coalesce(sum(attempts),0) FROM tickets WHERE tenant_id = :t) AS submission_attempts"),
        {"t": str(ctx.tenant_id)}).one()
    params = {"t": str(ctx.tenant_id)}

    def group(column: str, table: str) -> dict:
        extra = " AND lifecycle_status = 'active'" if table == "documents" else ""
        sql = f"SELECT {column}, count(*) FROM {table} WHERE tenant_id = :t{extra} GROUP BY {column}"
        return dict(ctx.session.execute(text(sql), params).all())

    retried = ctx.session.scalar(text("SELECT count(*) FROM tickets WHERE tenant_id = :t AND attempts > 1"), params)
    return {"incidents_by_review_status": group("review_status", "incidents"),
            "incidents_by_priority": group("priority", "incidents"),
            "outbox_by_status": group("status", "outbox_events"),
            "tickets_needing_retries": retried, "documents_by_kind": group("kind", "documents"),
            "tickets_by_state": by_state, "documents": counts.documents, "incidents": counts.incidents,
            "dead_letters": counts.dead_letters, "submission_attempts": int(counts.submission_attempts),
            "approvals_decided": turnaround.n,
            "avg_approval_turnaround_seconds": float(turnaround.avg_s) if turnaround.avg_s is not None else None}
