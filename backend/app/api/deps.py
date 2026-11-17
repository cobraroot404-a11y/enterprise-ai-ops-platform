"""Request authentication, tenant context and permission checks (server-side, on every route)."""
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rbac
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.models import Membership, User


@dataclass
class Ctx:
    session: Session
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    role: str
    correlation_id: str | None
    request: Request

    def commit(self) -> None:
        self.session.commit()


def _claims(request: Request, authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing bearer token")
    try:
        claims = decode_token(request.app.state.settings.jwt_secret, authorization.split(" ", 1)[1])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Token expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid token", code="invalid_token") from exc
    try:  # a signed token with malformed identifiers must be a 401, never a server error
        uuid.UUID(str(claims["sub"]))
        if claims.get("tid"):
            uuid.UUID(str(claims["tid"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise Unauthorized("Invalid token", code="invalid_token") from exc
    return claims


def tenant_ctx(permission: str):
    """Dependency factory: authenticates, re-checks membership/role in the DB, opens a tenant session."""

    def dependency(request: Request, authorization: str | None = Header(default=None)):
        claims = _claims(request, authorization)
        if not claims.get("tid"):
            raise Forbidden("This endpoint requires a tenant-scoped token")
        user_id, tenant_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["tid"])
        db = request.app.state.db
        with db.session(user_id=user_id) as own:  # RLS shows a user only their own memberships here
            membership = own.scalar(select(Membership).where(Membership.user_id == user_id,
                                                             Membership.tenant_id == tenant_id))
            role = membership.role if membership else None
        # Authorization uses the CURRENT database role, not the role claimed in the token.
        if role is None:
            raise Forbidden("No membership in this tenant")
        if not rbac.can(role, permission):
            raise Forbidden(f"Role '{role}' lacks permission '{permission}'", code="insufficient_role")
        session = db.session(tenant_id, user_id)
        try:
            yield Ctx(session, user_id, tenant_id, role, getattr(request.state, "correlation_id", None), request)
        finally:
            session.close()

    return dependency


def platform_admin_ctx():
    def dependency(request: Request, authorization: str | None = Header(default=None)):
        claims = _claims(request, authorization)
        user_id = uuid.UUID(claims["sub"])
        db = request.app.state.db
        session = db.session(user_id=user_id)
        try:
            user = session.scalar(select(User).where(User.id == user_id))
            if user is None or not user.is_platform_admin:
                raise Forbidden("Platform administrator required")
            yield Ctx(session, user_id, None, rbac.PLATFORM_ADMIN,
                      getattr(request.state, "correlation_id", None), request)
        finally:
            session.close()

    return dependency


def authenticated_user():
    def dependency(request: Request, authorization: str | None = Header(default=None)) -> dict:
        return _claims(request, authorization)

    return dependency
