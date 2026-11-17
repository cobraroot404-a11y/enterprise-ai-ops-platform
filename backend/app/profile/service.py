"""Load and save the tenant profile (RLS scopes every query to the current tenant)."""
import datetime as dt
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.models import TenantProfileRow
from app.profile.schema import TenantProfile


def get_profile(session: Session, tenant_id) -> TenantProfile | None:
    """The tenant's profile, or None to use the platform's built-in equipment-maintenance defaults."""
    row = session.scalar(select(TenantProfileRow).where(TenantProfileRow.tenant_id == tenant_id))
    return TenantProfile.model_validate(row.config) if row else None


def get_profile_row(session: Session, tenant_id) -> TenantProfileRow | None:
    return session.scalar(select(TenantProfileRow).where(TenantProfileRow.tenant_id == tenant_id))


def save_profile(session: Session, *, tenant_id, user_id, profile: TenantProfile, correlation_id=None) -> int:
    config = profile.model_dump(mode="json")
    row = session.scalar(select(TenantProfileRow).where(TenantProfileRow.tenant_id == tenant_id).with_for_update())
    if row is None:
        row = TenantProfileRow(tenant_id=tenant_id, version=1, config=config, updated_by=user_id)
        session.add(row)
    else:
        row.version += 1
        row.config, row.updated_by = config, user_id
        row.updated_at = dt.datetime.now(dt.timezone.utc)
    session.flush()
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    audit.record(session, tenant_id=tenant_id, actor_id=user_id, action="profile.updated", entity_type="tenant_profile",
                 entity_id=tenant_id, details={"version": row.version, "sha256": digest},
                 correlation_id=correlation_id)
    return row.version
