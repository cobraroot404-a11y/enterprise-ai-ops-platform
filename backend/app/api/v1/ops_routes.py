"""Operational read endpoints for the full UI: entity history, connector and onboarding health, evaluation evidence.

Nothing here is estimated: every number is computed from the tenant's own rows, from the server's connector
configuration, or read verbatim from evaluation artifacts committed under evaluation/.
"""

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text

from app.api.deps import Ctx, tenant_ctx
from app.api.v1.response_models import (
    ConnectorsHealth,
    EvaluationRegistry,
    EvaluationReports,
    IncidentHistory,
    ObservabilitySummary,
    OnboardingHealth,
    TicketHistory,
)
from app.connectors.egress import EgressDenied, get_policy, tenant_slug
from app.core.errors import NotFound
from app.models import Approval, AuditEvent, Connector, EvaluationRun, Incident, Ticket, User
from app.profile.service import get_profile_row

history_router = APIRouter(tags=["history"])
connectors_health_router = APIRouter(prefix="/connectors", tags=["connectors"])
onboarding_router = APIRouter(prefix="/onboarding", tags=["onboarding"])
evaluation_router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def _events(session, tenant_id, entity_id: str) -> list[dict]:
    rows = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.entity_id == entity_id)
        .order_by(AuditEvent.id)
    ).all()
    names = (
        {
            u.id: u.email
            for u in session.scalars(select(User).where(User.id.in_([r.actor_id for r in rows if r.actor_id])))
        }
        if rows
        else {}
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "actor": names.get(r.actor_id) or r.actor_type,
            "actor_type": r.actor_type,
            "details": r.details,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@history_router.get("/tickets/{ticket_id}/history", response_model=TicketHistory, response_model_exclude_unset=True)
def ticket_history(ticket_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("tickets:read"))):
    ticket = ctx.session.scalar(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == ctx.tenant_id))
    if ticket is None:
        raise NotFound("Ticket not found")
    approvals = ctx.session.scalars(
        select(Approval)
        .where(Approval.ticket_id == ticket.id, Approval.tenant_id == ctx.tenant_id)
        .order_by(Approval.decided_at)
    ).all()
    return {
        "ticket_id": str(ticket.id),
        "events": _events(ctx.session, ctx.tenant_id, str(ticket.id)),
        "approvals": [
            {
                "decision": a.decision,
                "decided_by": str(a.decided_by),
                "comment": a.comment,
                "decided_at": a.decided_at.isoformat(),
            }
            for a in approvals
        ],
    }


@history_router.get("/incidents/{incident_id}/history",
         response_model=IncidentHistory, response_model_exclude_unset=True)
def incident_history(incident_id: uuid.UUID, ctx: Ctx = Depends(tenant_ctx("incidents:read"))):
    incident = ctx.session.scalar(
        select(Incident).where(Incident.id == incident_id, Incident.tenant_id == ctx.tenant_id)
    )
    if incident is None:
        raise NotFound("Incident not found")
    tickets = ctx.session.scalars(
        select(Ticket).where(Ticket.incident_id == incident.id, Ticket.tenant_id == ctx.tenant_id)
    ).all()
    return {
        "incident_id": str(incident.id),
        "events": _events(ctx.session, ctx.tenant_id, str(incident.id)),
        "tickets": [{"id": str(t.id), "state": t.state, "external_ticket_id": t.external_ticket_id} for t in tickets],
    }


# ---- connector health (configuration and delivery results; no live probe) ----
def _live_probe(session, connector, slug, tenant_id, user_id, correlation_id) -> dict:
    """One bounded real request to a REST records source (opt-in; nothing ingested or changed upstream)."""
    from datetime import datetime, timezone

    from app.audit import service as audit
    from app.connectors.rest_records import SourceError, build_csv_source, build_source, parse_config, parse_csv_config
    from app.core.errors import Invalid
    try:
        if connector.kind == "csv":
            cfg = parse_csv_config(connector.config)
            result = build_csv_source(connector, cfg, tenant_slug=slug, timeout=3.0).probe()
        else:
            result = build_source(connector, parse_config(connector.config), tenant_slug=slug, timeout=3.0).probe()
    except (Invalid, SourceError):  # invalid configuration or a secret that is not set: nothing was sent
        result = {"status": "not_configured", "http_status": None, "duration_ms": 0.0}
    result["checked_at"] = datetime.now(timezone.utc).isoformat()
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="connector.probed", entity_type="connector",
                 entity_id=connector.id, details={"status": result["status"], "http_status": result["http_status"]},
                 correlation_id=correlation_id)
    return result


def connector_statuses(session, tenant_id, *, probe: bool = False, user_id=None, correlation_id=None) -> list[dict]:
    slug = tenant_slug(session, tenant_id)
    policy = get_policy()
    delivery = dict(
        session.execute(
            text("SELECT state, count(*) FROM tickets WHERE tenant_id = :t GROUP BY state"), {"t": str(tenant_id)}
        ).all()
    )
    last_ok = session.scalar(select(func.max(Ticket.submitted_at)).where(Ticket.tenant_id == tenant_id))
    last_err = session.execute(
        text(
            "SELECT last_error, updated_at FROM tickets WHERE tenant_id = :t AND last_error IS NOT NULL "
            "ORDER BY updated_at DESC LIMIT 1"
        ),
        {"t": str(tenant_id)},
    ).first()
    items = []
    for c in session.scalars(
        select(Connector).where(Connector.tenant_id == tenant_id).order_by(Connector.kind, Connector.name)
    ):
        try:
            policy.authorize(c.base_url, slug)
            authorized, reason = True, None
        except EgressDenied as exc:
            authorized, reason = False, exc.reason
        secret_ok = None if not c.secret_ref else os.environ.get(c.secret_ref) is not None
        item = {
            "id": str(c.id),
            "kind": c.kind,
            "name": c.name,
            "base_url": c.base_url,
            "destination_authorized": authorized,
            "destination_reason": reason,
            "secret_configured": secret_ok,
            "has_secret_ref": bool(c.secret_ref),
            "probe": "none: status reflects configuration and recent delivery results, not a live request",
        }
        status = "ok"
        if not authorized or secret_ok is False:
            status = "blocked"
        if c.kind == "ticketing":
            failing = delivery.get("FAILED", 0) + delivery.get("RETRY_PENDING", 0)
            item["delivery"] = {
                "submitted": delivery.get("SUBMITTED", 0),
                "failed": delivery.get("FAILED", 0),
                "retry_pending": delivery.get("RETRY_PENDING", 0),
                "submitting": delivery.get("SUBMITTING", 0),
                "last_success_at": last_ok.isoformat() if last_ok else None,
                "last_error": last_err[0] if last_err else None,
            }
            if status == "ok" and failing:
                status = "degraded"
        cfg_key = {"rest": "records", "csv": "csv"}.get(c.kind)
        if probe and cfg_key and isinstance((c.config or {}).get(cfg_key), dict):
            item["live_probe"] = _live_probe(session, c, slug, tenant_id, user_id, correlation_id)
            item["probe"] = "live: one bounded request was made to the source (see live_probe)"
            if status == "ok" and item["live_probe"]["status"] != "ok":
                status = "degraded"
        item["status"] = status
        items.append(item)
    return items


@connectors_health_router.get("/health", response_model=ConnectorsHealth, response_model_exclude_unset=True)
def connectors_health(probe: bool = Query(False, description="Opt in: one bounded live request per REST connector"),
                      ctx: Ctx = Depends(tenant_ctx("connectors:read"))):
    items = connector_statuses(ctx.session, ctx.tenant_id, probe=probe, user_id=ctx.user_id,
                               correlation_id=ctx.correlation_id)
    if probe:
        ctx.commit()  # the probe audit events
    return {"items": items}


@onboarding_router.get("/health", response_model=OnboardingHealth, response_model_exclude_unset=True)
def onboarding_health(ctx: Ctx = Depends(tenant_ctx("profile:read"))):
    """Onboarding checklist derived from real configuration; each check says what it looked at."""
    s, t = ctx.session, str(ctx.tenant_id)
    row = get_profile_row(s, ctx.tenant_id)
    checks = []

    def add(cid, label, ok, detail):
        checks.append({"id": cid, "label": label, "status": "pass" if ok else "fail", "detail": detail})

    kinds = {
        r[0]: r[1]
        for r in s.execute(
            text("SELECT d.kind, count(*) FROM documents d "
                 "WHERE d.tenant_id = :t AND d.lifecycle_status = 'active' GROUP BY d.kind"), {"t": t}
        )
    }
    register_kind = row.config.get("register_kind") if row else "equipment_register"
    guidance = (row.config.get("guidance_kinds") if row else ["equipment_manual", "inspection_report"]) or []
    add(
        "profile",
        "Domain profile configured (or platform defaults in use)",
        True,
        f"profile version {row.version}" if row else "no profile: the built-in equipment-maintenance defaults apply",
    )
    add(
        "register",
        f"Authoritative asset register ingested ({register_kind})",
        kinds.get(register_kind, 0) > 0,
        f"{kinds.get(register_kind, 0)} document(s)",
    )
    add(
        "guidance",
        "Guidance documents ingested",
        any(kinds.get(k, 0) for k in guidance),
        ", ".join(f"{k}: {kinds.get(k, 0)}" for k in guidance),
    )
    embed = s.execute(
        text("SELECT provider, model FROM embedding_profiles WHERE tenant_id = :t AND active"), {"t": t}
    ).first()
    add(
        "embedding",
        "Active embedding profile recorded",
        embed is not None,
        f"{embed[0]} / {embed[1]}" if embed else "no documents ingested yet",
    )
    members = {
        r[0]: r[1]
        for r in s.execute(text("SELECT role, count(*) FROM memberships WHERE tenant_id = :t GROUP BY role"), {"t": t})
    }
    add(
        "approvers",
        "At least one approver (supervisor or admin) besides the ticket authors",
        members.get("maintenance_supervisor", 0) + members.get("tenant_admin", 0) > 0,
        json.dumps(members),
    )
    if ctx.role == "tenant_admin":
        connectors = connector_statuses(s, ctx.tenant_id)
        ticketing = [c for c in connectors if c["kind"] == "ticketing"]
        add("ticketing", "Ticketing connector configured", bool(ticketing), f"{len(ticketing)} connector(s)")
        add(
            "destinations",
            "All connector destinations authorized by the server egress policy",
            all(c["destination_authorized"] for c in connectors) and bool(connectors),
            "; ".join(
                f"{c['name']}: {'authorized' if c['destination_authorized'] else c['destination_reason']}"
                for c in connectors
            ),
        )
        add(
            "secrets",
            "Connector secrets resolvable on the server",
            all(c["secret_configured"] is not False for c in connectors),
            "secret references only; values are never shown",
        )
    else:
        checks.append(
            {
                "id": "connectors",
                "label": "Connector checks",
                "status": "unavailable",
                "detail": "connector configuration is visible to tenant administrators only",
            }
        )
    ok = [c for c in checks if c["status"] != "unavailable"]
    return {"checks": checks, "passed": sum(1 for c in ok if c["status"] == "pass"), "total": len(ok)}


# ---- evaluation evidence (read verbatim from committed artifacts) ---------------------------------------------------
TARGETS = [  # initial proposed targets from the V4.1 specification: targets, NOT achieved results
    {"id": "recall_at_5", "label": "Retrieval Recall@5", "op": ">=", "value": 0.85},
    {"id": "citation_correctness", "label": "Citation correctness", "op": ">=", "value": 0.95},
    {"id": "structured_validity", "label": "Structured output validity", "op": ">=", "value": 1.0},
    {"id": "duplicate_tickets", "label": "Duplicate tickets during tested workflows", "op": "==", "value": 0},
]


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run_summary(run_dir: Path, group: str) -> dict | None:
    results, manifest = _load(run_dir / "results.json"), _load(run_dir / "manifest.json")
    if not results or not manifest:
        return None
    ret, qa, st, e2e = (
        (results.get("retrieval") or {}).get("test") or {},
        results.get("qa") or {},
        results.get("structured") or {},
        results.get("e2e") or {},
    )
    n_unans = qa.get("unanswerable_queries") or 0
    return {
        "id": run_dir.name,
        "group": group,
        "evidence_class": results.get("evidence_class"),
        "backends": results.get("backends"),
        "dataset": (manifest.get("dataset") or {}).get("name"),
        "started_utc": manifest.get("started_utc"),
        "command": manifest.get("command"),
        "hardware": {k: (manifest.get("hardware") or {}).get(k) for k in ("cpu", "ram_gb", "os", "gpu")},
        "versions": {
            k: (results.get("versions") or {}).get(k)
            for k in ("ollama", "ollama_model", "ollama_model_digest", "embedding_profile", "python", "postgres")
        },
        "has_note": (run_dir / "NOTE.md").exists(),
        "metrics": {
            "recall_at_5": ret.get("recall_at_5"),
            "mrr": ret.get("mrr"),
            "precision_at_5": ret.get("precision_at_5"),
            "citation_correctness": qa.get("citation_correctness"),
            "groundedness_rate": qa.get("groundedness_rate"),
            "correct_refusals": f"{qa.get('correct_abstentions')}/{n_unans}" if n_unans else None,
            "structured_validity": st.get("model_output_validity_rate"),
            "duplicate_tickets": e2e.get("duplicates"),
            "llm_inference_median_s": (qa.get("llm_inference_s") or {}).get("median"),
            "llm_inference_p95_s": (qa.get("llm_inference_s") or {}).get("p95"),
            "e2e_median_s": (e2e.get("total_s") or {}).get("median"),
            "e2e_p95_s": (e2e.get("total_s") or {}).get("p95"),
        },
    }


@evaluation_router.get("/registry", response_model=EvaluationRegistry, response_model_exclude_unset=True)
def evaluation_registry(
    suite: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: Ctx = Depends(tenant_ctx("metrics:read")),
):
    """Read-only index of evaluation runs (migration 0014). Platform evidence, not tenant data: the table has no tenant column and the application roles hold SELECT only."""
    q = select(EvaluationRun)
    if suite:
        q = q.where(EvaluationRun.suite == suite)
    total = ctx.session.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.session.scalars(
        q.order_by(EvaluationRun.started_at.desc().nulls_last(), EvaluationRun.run_id).limit(limit).offset(offset)
    ).all()
    iso = lambda v: v.isoformat() if v else None  # noqa: E731
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "run_id": r.run_id, "suite": r.suite, "label": r.label, "command": r.command, "dataset": r.dataset,
                "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "duration_s": r.duration_s,
                "git_commit": r.git_commit, "manifest_path": r.manifest_path, "manifest_sha256": r.manifest_sha256,
            }
            for r in rows
        ],
    }


@evaluation_router.get("/reports", response_model=EvaluationReports, response_model_exclude_unset=True)
def evaluation_reports(request: Request, ctx: Ctx = Depends(tenant_ctx("metrics:read"))):
    base = Path(request.app.state.settings.evaluation_dir) / "reports"
    runs = []
    for group in ("phase3", "phase4-remeasure"):
        for d in sorted((base / group).glob("*_*")) if (base / group).is_dir() else []:
            summary = _run_summary(d, group)
            if summary:
                runs.append(summary)
    smoke = []
    for d in sorted(base.glob("*smoke*/*_smoke")) if base.is_dir() else []:
        checks, manifest = _load(d / "checks.json"), _load(d / "manifest.json")
        if checks and manifest:
            smoke.append(
                {
                    "id": d.name,
                    "label": manifest.get("label"),
                    "started_utc": manifest.get("started_utc"),
                    "checks_passed": sum(1 for c in checks if c["passed"]),
                    "checks_total": len(checks),
                    "failed": [c["id"] for c in checks if not c["passed"]],
                    "models": {
                        k: (manifest.get("versions") or {}).get(k) for k in ("ollama_model", "embedding_profile")
                    },
                }
            )
    fi = _load(Path(request.app.state.settings.evaluation_dir) / "failure-reports" / "phase4" / "fi-report.json")
    fault = None
    if isinstance(fi, dict) and isinstance(fi.get("summary"), dict):
        fault = {
            "scenarios": fi["summary"].get("scenarios"),
            "passed": fi["summary"].get("passed"),
            "failed": fi["summary"].get("failed"),
            "generated_utc": fi.get("generated_utc"),
            "items": [
                {"id": s.get("id"), "name": s.get("name"), "passed": s.get("passed")}
                for s in fi.get("scenarios", [])
                if isinstance(s, dict)
            ],
            "source": "evaluation/failure-reports/phase4/fi-report.json",
        }
    real = [r for r in runs if r["evidence_class"] == "real_ai"]
    measured = []
    for target in TARGETS:
        values = [r["metrics"].get(target["id"]) for r in real if r["metrics"].get(target["id"]) is not None]
        if not values:
            measured.append({**target, "status": "not measured", "actual": None})
            continue
        ok_all = all(v >= target["value"] if target["op"] == ">=" else v == target["value"] for v in values)
        measured.append(
            {
                **target,
                "actual": {"min": min(values), "max": max(values), "runs": len(values)},
                "status": "MET" if ok_all else "NOT MET",
            }
        )
    return {
        "available": bool(runs or smoke),
        "disclaimer": "Measured on the synthetic apex-eval-v1 dataset (author-written labels, "
        "small corpus). Targets are proposals, not results. Deterministic-backend runs are functional only, not AI "
        "performance. Smoke runs are functional checks only.",
        "targets": measured,
        "runs": runs,
        "smoke": smoke,
        "fault_injection": fault,
    }


# ---- observability summary (this tenant only) ----
observability_router = APIRouter(prefix="/observability", tags=["observability"])


def _error_class(message: str | None) -> str:
    head = (message or "").split(":", 1)[0].strip().lower()
    if head in ("transient", "permanent", "malformed"):
        return head
    if "destination not permitted" in (message or ""):
        return "denied"
    return "other" if message else "none"


@observability_router.get("/summary", response_model=ObservabilitySummary, response_model_exclude_unset=True)
def observability_summary(ctx: Ctx = Depends(tenant_ctx("metrics:read"))):
    """Operational telemetry for the caller tenant: process metrics (this API process) plus durable database counts.

    Nothing here is estimated or synthetic: when no activity occurred the series are simply absent. Labels carry the
    tenant id and technical dimensions only; no document text, user input or credentials are ever recorded.
    """
    from app.observability.metrics import METRICS

    s, t = ctx.session, str(ctx.tenant_id)

    def rows(sql: str) -> list:
        return s.execute(text(sql), {"t": t}).all()

    audit_counts = {
        a: n
        for a, n in rows(
            "SELECT action, count(*) FROM audit_events WHERE tenant_id = :t AND action IN ('ticket.submitted', "
            "'submission.retry_scheduled', 'submission.dead_lettered', 'submission.blocked', 'incident.review_accept', "
            "'incident.review_reject', 'incident.extracted', 'approval.approved', 'approval.rejected') GROUP BY action"
        )
    }
    transitions = [
        {"from": f, "to": to, "count": n}
        for f, to, n in rows(
            "SELECT details->>'from', details->>'to', count(*) FROM audit_events WHERE tenant_id = :t "
            "AND action = 'ticket.transition' GROUP BY 1, 2 ORDER BY 1, 2"
        )
    ]
    errors: dict[str, int] = {}
    for (msg,) in rows("SELECT last_error FROM tickets WHERE tenant_id = :t AND last_error IS NOT NULL"):
        errors[_error_class(msg)] = errors.get(_error_class(msg), 0) + 1
    extracted = audit_counts.get("incident.extracted", 0)
    needs = (
        s.scalar(
            text("SELECT count(*) FROM incidents WHERE tenant_id = :t AND review_status = 'needs_review'"), {"t": t}
        )
        or 0
    )
    # An incident "required review" if it ever left pending_review (it is now awaiting review, accepted or rejected).
    required = (
        s.scalar(
            text("SELECT count(*) FROM incidents WHERE tenant_id = :t AND review_status <> 'pending_review'"), {"t": t}
        )
        or 0
    )
    pending_or_accepted = extracted - required
    return {
        "scope": "process metrics cover this API process since it started; database figures are durable",
        "process": METRICS.snapshot(tenant=t),
        "database": {
            "submission": {
                "submitted": audit_counts.get("ticket.submitted", 0),
                "retries_scheduled": audit_counts.get("submission.retry_scheduled", 0),
                "dead_lettered": audit_counts.get("submission.dead_lettered", 0),
                "blocked_by_release_controls": audit_counts.get("submission.blocked", 0),
            },
            "incident_review": {
                "extracted": extracted,
                "needs_review_now": needs,
                "required_review": required,
                "review_required_rate": round(required / extracted, 4) if extracted else None,
                "accepted": audit_counts.get("incident.review_accept", 0),
                "rejected": audit_counts.get("incident.review_reject", 0),
                "cleared_without_review": pending_or_accepted,
            },
            "approvals": {
                "approved": audit_counts.get("approval.approved", 0),
                "rejected": audit_counts.get("approval.rejected", 0),
            },
            "ticket_transitions": transitions,
            "ticket_error_classes": errors,
        },
    }


# ---- Prometheus text exposition (root path, deliberately outside the typed JSON API contract and the OpenAPI schema) ---------------------------------------
prometheus_router = APIRouter(include_in_schema=False)


@prometheus_router.get("/metrics")
def prometheus_metrics(request: Request, ctx: Ctx = Depends(tenant_ctx("metrics:read"))):
    """Durable operational metrics in Prometheus text format: this tenant's series plus platform-level series (never another tenant's).

    Authenticated like every other operation (bearer token with `metrics:read`; Prometheus can send it with `authorization`). The serving process flushes first, so its own activity is
    included; other processes (the worker) flush every few seconds, so their activity can lag by that interval. Series survive restarts and sum across processes.
    """
    from fastapi.responses import PlainTextResponse

    from app.observability.metrics import METRICS, read_durable, render_prometheus

    METRICS.flush(request.app.state.db)
    series = read_durable(ctx.session, str(ctx.tenant_id))
    return PlainTextResponse(render_prometheus(series), media_type="text/plain; version=0.0.4; charset=utf-8")
