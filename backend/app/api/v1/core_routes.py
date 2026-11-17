"""Auth, tenants, members, connectors, health."""
import re
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import Ctx, authenticated_user, platform_admin_ctx, tenant_ctx
from app.api.v1.response_models import (
    ConnectorCreated,
    ConnectorsList,
    HealthResponse,
    IngestionJobOut,
    LoginResponse,
    MemberChange,
    MemberRemoved,
    MembersList,
    MeResponse,
    Page,
    PlatformAuditItem,
    TenantCreated,
    TenantsMine,
)
from app.audit import service as audit
from app.connectors.egress import EgressDenied, get_policy, tenant_slug
from app.core import rbac
from app.core.errors import AppError, Conflict, Forbidden, Invalid, NotFound, Unauthorized
from app.core.production_guard import reject_test_credentials
from app.core.security import create_token, hash_password, verify_password
from app.models import Connector, Membership, Tenant, User

auth_router = APIRouter(prefix="/auth", tags=["auth"])
tenants_router = APIRouter(prefix="/tenants", tags=["tenants"])
platform_router = APIRouter(prefix="/platform", tags=["platform"])
connectors_router = APIRouter(prefix="/connectors", tags=["connectors"])
health_router = APIRouter(prefix="/health", tags=["health"])

_DUMMY_HASH = hash_password("not-a-real-password")

# Login brute-force throttle: at most MAX_FAILURES failed attempts per account per WINDOW seconds.
MAX_FAILURES, WINDOW_SECONDS = 10, 60
_failures: dict[str, deque] = defaultdict(deque)
_failures_lock = threading.Lock()


def _shared(call):
    """Run a shared-store operation; None when no store is configured or it is unavailable (the process-local counter below always runs too, so the throttle never disappears)."""
    from app.connectors.ratelimit import LIMITERS, StoreUnavailable

    store = LIMITERS.usable_store()
    if store is None:
        return None
    try:
        return call(store)
    except StoreUnavailable:
        LIMITERS.store_failed()
        return None


def _throttled(key: str) -> int | None:
    """Seconds to wait if the account is currently throttled (by this process or, through the database, by any other), else None."""
    shared = _shared(lambda s: s.window_wait(f"login:{key}", WINDOW_SECONDS, MAX_FAILURES)) or 0
    now = time.monotonic()
    with _failures_lock:
        attempts = _failures[key]
        while attempts and now - attempts[0] > WINDOW_SECONDS:
            attempts.popleft()
        local = int(WINDOW_SECONDS - (now - attempts[0])) + 1 if len(attempts) >= MAX_FAILURES else 0
    return max(shared, local) or None


def _record_failure(key: str) -> None:
    _shared(lambda s: s.window_add(f"login:{key}", WINDOW_SECONDS))
    with _failures_lock:
        _failures[key].append(time.monotonic())


def _clear_failures(key: str) -> None:
    _shared(lambda s: s.window_clear(f"login:{key}"))
    with _failures_lock:
        _failures.pop(key, None)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    tenant: str | None = Field(default=None, max_length=60)


@auth_router.post("/login", response_model=LoginResponse, response_model_exclude_unset=True)
def login(body: LoginRequest, request: Request):
    settings, db = request.app.state.settings, request.app.state.db
    reject_test_credentials(body.password)  # known test passwords are never accepted in production
    key = body.email.lower().strip()
    wait = _throttled(key)
    if wait:
        raise AppError("Too many failed sign-in attempts; try again later", code="too_many_attempts",
                       status_code=429, retry_after=wait)
    with db.session() as session:
        # Exact-match credential lookup through a narrow database function: the API role cannot scan users.
        user = session.execute(text("SELECT * FROM auth_find_user(:e)"), {"e": key}).first()
        ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)  # constant-ish time
        if not user or not ok:
            _record_failure(key)
            raise Unauthorized("Invalid credentials", code="invalid_credentials")
        _clear_failures(key)
        uid, is_admin, email, full_name = user.id, user.is_platform_admin, user.email, user.full_name
    tenant_id, role = None, None
    if body.tenant:
        with db.session(user_id=uid) as session:  # sees only the caller's own memberships
            tenant = session.scalar(select(Tenant).where(Tenant.slug == body.tenant))
            membership = session.scalar(select(Membership).where(
                Membership.user_id == uid, Membership.tenant_id == (tenant.id if tenant else None)))
            if not tenant or not membership:
                raise Unauthorized("Invalid credentials", code="invalid_credentials")
            tenant_id, role = tenant.id, membership.role
    elif is_admin:
        role = rbac.PLATFORM_ADMIN
        with db.session(user_id=uid) as session:  # platform-level sign-ins are audited (tenant-less audit row)
            audit.record(session, tenant_id=None, actor_id=uid, action="platform.login", entity_type="user",
                         entity_id=uid, details={"email": email}, correlation_id=getattr(request.state,
                                                                                         "correlation_id", None))
            session.commit()
    else:
        raise Unauthorized("A tenant is required for this account", code="tenant_required")
    token = create_token(settings.jwt_secret, uid, tenant_id, role, settings.jwt_expire_minutes)
    return {"access_token": token, "token_type": "bearer", "role": role,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "user": {"id": str(uid), "email": email, "full_name": full_name}}


@auth_router.get("/me", response_model=MeResponse, response_model_exclude_unset=True)
def me(request: Request, claims: dict = Depends(authenticated_user())):
    db = request.app.state.db
    uid = uuid.UUID(claims["sub"])
    with db.session(user_id=uid) as session:
        user = session.get(User, uid)
        if not user:
            raise Unauthorized("Unknown user")
        role = claims.get("role")
        if claims.get("tid"):
            membership = session.scalar(select(Membership).where(
                Membership.user_id == uid, Membership.tenant_id == uuid.UUID(claims["tid"])))
            role = membership.role if membership else None
        return {"id": str(user.id), "email": user.email, "full_name": user.full_name, "role": role,
                "tenant_id": claims.get("tid"), "is_platform_admin": user.is_platform_admin}


class TenantCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")
    name: str = Field(min_length=2, max_length=120)


@tenants_router.post("", status_code=201, response_model=TenantCreated, response_model_exclude_unset=True)
def create_tenant(body: TenantCreate, ctx: Ctx = Depends(platform_admin_ctx())):
    try:  # only a platform admin passes the check inside this database function
        tenant_id = ctx.session.execute(text("SELECT app_create_tenant(:s, :n)"),
                                        {"s": body.slug, "n": body.name}).scalar_one()
    except IntegrityError as exc:
        ctx.session.rollback()
        raise Conflict("Tenant slug already exists") from exc
    ctx.commit()
    ctx.session.info["tenant_id"] = str(tenant_id)  # audit rows are tenant-scoped under RLS
    audit.record(ctx.session, tenant_id=tenant_id, actor_id=ctx.user_id, action="tenant.created",
                 entity_type="tenant", entity_id=tenant_id, details={"slug": body.slug},
                 correlation_id=ctx.correlation_id)
    ctx.commit()
    return {"id": str(tenant_id), "slug": body.slug, "name": body.name}


@platform_router.get("/audit", response_model=Page[PlatformAuditItem], response_model_exclude_unset=True)
def platform_audit(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                   ctx: Ctx = Depends(platform_admin_ctx())):
    """Platform-level (tenant-less) audit trail: administrator sign-ins. Same pagination envelope as every list."""
    total = ctx.session.execute(text("SELECT count(*) FROM audit_events WHERE tenant_id IS NULL")).scalar()
    rows = ctx.session.execute(text(
        "SELECT id, actor_id, action, details, created_at FROM audit_events WHERE tenant_id IS NULL "
        "ORDER BY id DESC LIMIT :n OFFSET :o"), {"n": limit, "o": offset}).all()
    items = [{"id": r.id, "actor_id": str(r.actor_id), "action": r.action, "details": r.details,
              "created_at": r.created_at.isoformat()} for r in rows]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@tenants_router.get("/mine", response_model=TenantsMine, response_model_exclude_unset=True)
def my_tenants(request: Request, claims: dict = Depends(authenticated_user())):
    uid = uuid.UUID(claims["sub"])
    with request.app.state.db.session(user_id=uid) as session:
        rows = session.execute(
            select(Tenant, Membership.role).join(Membership, Membership.tenant_id == Tenant.id)
            .where(Membership.user_id == uid)).all()
        return {"items": [{"id": str(t.id), "slug": t.slug, "name": t.name, "role": r} for t, r in rows]}


# ---- member administration ----------------------------------------------------------------------------
def _admin_session(request: Request, claims: dict, tenant_id: uuid.UUID):
    """Authorize and return a session scoped to `tenant_id` with the actor's user context.

    Platform admins may administer any tenant; tenant admins only the tenant their token is for.
    The database policies enforce the same boundary independently (tenant context + no self-edits).
    """
    db = request.app.state.db
    actor_id = uuid.UUID(claims["sub"])
    with db.session(user_id=actor_id) as own:
        actor = own.get(User, actor_id)
        if actor is None:
            raise Unauthorized("Unknown user")
        if not actor.is_platform_admin:
            membership = own.scalar(select(Membership).where(Membership.user_id == actor_id,
                                                             Membership.tenant_id == tenant_id))
            if (not membership or not rbac.can(membership.role, "members:write")
                    or str(tenant_id) != claims.get("tid")):
                raise Forbidden("Not allowed to manage members of this tenant")
        if own.get(Tenant, tenant_id) is None:
            raise NotFound("Tenant not found")
        platform_admin = actor.is_platform_admin
    session = db.session(tenant_id, actor_id)
    if platform_admin:  # cross-tenant administration by a platform admin is always visible to the tenant
        audit.record(session, tenant_id=tenant_id, actor_id=actor_id, action="platform.tenant_access",
                     entity_type="tenant", entity_id=tenant_id, details={"via": "member administration"})
        session.commit()
    return session, actor_id


def member_admin_ctx(tenant_id: uuid.UUID, request: Request, claims: dict = Depends(authenticated_user())):
    """Dependency: authorize member administration before the request body is validated."""
    session, actor_id = _admin_session(request, claims, tenant_id)
    try:
        yield session, actor_id
    finally:
        session.close()


class MemberCreate(BaseModel):
    email: str = Field(max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=200)
    role: str


class MemberUpdate(BaseModel):
    role: str


def _check_role(role: str) -> None:
    if role not in rbac.TENANT_ROLES:
        raise Forbidden("Unknown or non-assignable role", code="invalid_role")


@tenants_router.get("/{tenant_id}/members", response_model=MembersList, response_model_exclude_unset=True)
def list_members(tenant_id: uuid.UUID, ctx=Depends(member_admin_ctx)):
    session, _ = ctx
    rows = session.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                           .where(Membership.tenant_id == tenant_id)).all()
    return {"items": [{"user_id": str(u.id), "email": u.email, "full_name": u.full_name, "role": m.role}
                      for m, u in rows]}


@tenants_router.post("/{tenant_id}/members", status_code=201,
         response_model=MemberChange, response_model_exclude_unset=True)
def add_member(tenant_id: uuid.UUID, body: MemberCreate, ctx=Depends(member_admin_ctx)):
    session, actor_id = ctx
    _check_role(body.role)
    email = body.email.lower().strip()
    # The database function re-checks that the caller administers this tenant and can never create a
    # platform admin; an existing account is reused (its password and name are never changed here).
    user_id = session.execute(text("SELECT app_provision_user(:e, :n, :p)"),
                              {"e": email, "n": body.full_name, "p": hash_password(body.password)}).scalar_one()
    if user_id == actor_id:
        raise Forbidden("You cannot assign roles to yourself", code="self_assignment")
    try:
        session.add(Membership(tenant_id=tenant_id, user_id=user_id, role=body.role))
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("User is already a member of this tenant") from exc
    audit.record(session, tenant_id=tenant_id, actor_id=actor_id, action="member.added",
                 entity_type="user", entity_id=user_id, details={"role": body.role, "email": email})
    session.commit()
    return {"user_id": str(user_id), "role": body.role}


@tenants_router.patch("/{tenant_id}/members/{user_id}", response_model=MemberChange, response_model_exclude_unset=True)
def change_member_role(tenant_id: uuid.UUID, user_id: uuid.UUID, body: MemberUpdate,
                       ctx=Depends(member_admin_ctx)):
    session, actor_id = ctx
    _check_role(body.role)
    if user_id == actor_id:
        raise Forbidden("You cannot change your own role", code="self_modification")
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant_id,
                                                         Membership.user_id == user_id))
    if membership is None:
        raise NotFound("Member not found")
    previous, membership.role = membership.role, body.role
    audit.record(session, tenant_id=tenant_id, actor_id=actor_id, action="member.role_changed",
                 entity_type="user", entity_id=user_id, details={"from": previous, "to": body.role})
    session.commit()
    return {"user_id": str(user_id), "role": body.role}


@tenants_router.delete("/{tenant_id}/members/{user_id}",
         response_model=MemberRemoved, response_model_exclude_unset=True)
def remove_member(tenant_id: uuid.UUID, user_id: uuid.UUID, ctx=Depends(member_admin_ctx)):
    session, actor_id = ctx
    if user_id == actor_id:
        raise Forbidden("You cannot remove your own membership", code="self_modification")
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant_id,
                                                         Membership.user_id == user_id))
    if membership is None:
        raise NotFound("Member not found")
    session.delete(membership)
    audit.record(session, tenant_id=tenant_id, actor_id=actor_id, action="member.removed",
                 entity_type="user", entity_id=user_id)
    session.commit()
    return {"removed": str(user_id)}


# ---- connectors ---------------------------------------------------------------------------------------
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9_\-./]{0,120}$")
_CANONICAL_FIELDS = {"title", "description", "priority", "asset_id", "source_ticket_id"}


def _validate_ticketing_config(config: dict) -> None:
    """Ticketing connector config describes the remote API contract; it is validated, never executed."""
    unknown = set(config) - {"create_path", "id_field", "payload_map", "priority_map"}
    if unknown:
        raise ValueError(f"unknown ticketing config keys: {sorted(unknown)}")
    path = config.get("create_path")
    if path is not None and (not isinstance(path, str) or not _SAFE_PATH.match(path) or "//" in path or ".." in path):
        raise ValueError("create_path must be a simple absolute path (no scheme, '//' or '..')")
    id_field = config.get("id_field")
    if id_field is not None and not (isinstance(id_field, str) and _IDENT.match(id_field)):
        raise ValueError("id_field must be an identifier")
    payload_map = config.get("payload_map")
    if payload_map is not None:
        if (not isinstance(payload_map, dict) or not set(payload_map) <= _CANONICAL_FIELDS
                or not all(isinstance(v, str) and _IDENT.match(v) for v in payload_map.values())):
            raise ValueError(f"payload_map keys must be among {sorted(_CANONICAL_FIELDS)} with identifier values")
    priority_map = config.get("priority_map")
    if priority_map is not None:
        if (not isinstance(priority_map, dict) or not set(priority_map) <= {"P1", "P2", "P3", "P4"}
                or not all(isinstance(v, str) and 0 < len(v) <= 30 for v in priority_map.values())):
            raise ValueError("priority_map must map P1..P4 to short strings")


class ConnectorCreate(BaseModel):
    kind: str = Field(pattern="^(ticketing|inventory|crm|fleet|rest|csv|webhook)$")
    name: str = Field(min_length=2, max_length=60)
    base_url: str = Field(pattern=r"^https?://[^\s]+$", max_length=300)
    secret_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,60}$")
    config: dict = {}

    @model_validator(mode="after")
    def _config(self):
        if self.kind == "ticketing":
            _validate_ticketing_config(self.config)
        elif isinstance(self.config.get("records"), dict):  # REST records connector: validated when saved
            from app.connectors.rest_records import parse_config
            if self.kind != "rest":
                raise ValueError("a records configuration belongs to a rest connector")
            try:
                parse_config(self.config)
            except Invalid as exc:
                raise ValueError(str(exc)) from exc
        elif isinstance(self.config.get("csv"), dict):  # CSV connector: validated when saved
            from app.connectors.rest_records import parse_csv_config
            if self.kind != "csv":
                raise ValueError("a csv configuration belongs to a csv connector")
            try:
                parse_csv_config(self.config)
            except Invalid as exc:
                raise ValueError(str(exc)) from exc
        elif len(str(self.config)) > 2000:
            raise ValueError("config is too large")
        return self


@connectors_router.get("", response_model=ConnectorsList, response_model_exclude_unset=True)
def list_connectors(ctx: Ctx = Depends(tenant_ctx("connectors:read"))):
    rows = ctx.session.scalars(select(Connector).where(Connector.tenant_id == ctx.tenant_id)).all()
    return {"items": [{"id": str(c.id), "kind": c.kind, "name": c.name, "base_url": c.base_url,
                       "has_secret": bool(c.secret_ref), "config": c.config} for c in rows]}


@connectors_router.post("/{connector_id}/sync", status_code=202, response_model=IngestionJobOut,
                        response_model_exclude_unset=True)
def sync_connector(connector_id: uuid.UUID, request: Request, ctx: Ctx = Depends(tenant_ctx("connectors:sync"))):
    """Queue a synchronisation of a tenant's REST records connector (administrator or supervisor).

    202 is sent only after the durable job was committed; the worker pulls the records through the approved
    connector and ingests them, and the job (GET /ingestion/jobs/{id}) reports the real outcome. There is no
    request body: destination, credentials and paths come only from the stored connector, so a caller can not
    redirect the pull. Another tenant's connector id is a 404."""
    from app.ai.embeddings import get_embedder
    from app.ingestion import jobs as ingestion_jobs
    from app.ingestion import sync
    from app.profile.service import get_profile
    profile = get_profile(ctx.session, ctx.tenant_id)
    embedder = get_embedder(request.app.state.settings.embedding_backend)
    kinds = profile.allowed_kinds() if profile else frozenset()
    job = sync.request_sync(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, connector_id=connector_id,
                            embedder=embedder, allowed_kinds=kinds, correlation_id=ctx.correlation_id)
    ctx.commit()
    return ingestion_jobs.job_out(job)


@connectors_router.post("", status_code=201, response_model=ConnectorCreated, response_model_exclude_unset=True)
def create_connector(body: ConnectorCreate, ctx: Ctx = Depends(tenant_ctx("connectors:write"))):
    try:  # the destination must be on the SERVER's allow-list for this tenant; admins cannot widen it
        get_policy().check_config(body.base_url, tenant_slug(ctx.session, ctx.tenant_id))
    except EgressDenied as exc:
        raise Invalid(f"Connector destination rejected: {exc.reason}",
                      code="connector_destination_not_allowed") from exc
    connector = Connector(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.session.add(connector)
    try:
        ctx.session.flush()
    except IntegrityError as exc:
        ctx.session.rollback()
        raise Conflict("Connector already exists") from exc
    audit.record(ctx.session, tenant_id=ctx.tenant_id, actor_id=ctx.user_id, action="connector.created",
                 entity_type="connector", entity_id=connector.id,
                 details={"kind": body.kind, "name": body.name}, correlation_id=ctx.correlation_id)
    ctx.commit()
    return {"id": str(connector.id), "kind": connector.kind, "name": connector.name}


@health_router.get("", response_model=HealthResponse, response_model_exclude_unset=True)
def health(request: Request):
    with request.app.state.db.session() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok", "llm_backend": request.app.state.settings.llm_backend,
            "embedding_backend": request.app.state.settings.embedding_backend}
