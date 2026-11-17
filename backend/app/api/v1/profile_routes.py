"""Tenant profile endpoints (configuration that replaces hardcoded domain behaviour)."""
from fastapi import APIRouter, Depends

from app.api.deps import Ctx, tenant_ctx
from app.api.v1.response_models import ProfileRead, ProfileSaved
from app.profile.schema import TenantProfile
from app.profile.service import get_profile_row, save_profile

profile_router = APIRouter(prefix="/tenant-profile", tags=["tenant-profile"])


@profile_router.get("", response_model=ProfileRead, response_model_exclude_unset=True)
def read_profile(ctx: Ctx = Depends(tenant_ctx("profile:read"))):
    row = get_profile_row(ctx.session, ctx.tenant_id)
    if row is None:
        return {"version": 0, "using_defaults": True, "profile": None, "updated_at": None}
    return {"version": row.version, "using_defaults": False, "profile": row.config,
            "updated_at": row.updated_at.isoformat()}


@profile_router.put("", response_model=ProfileSaved, response_model_exclude_unset=True)
def replace_profile(body: TenantProfile, ctx: Ctx = Depends(tenant_ctx("profile:write"))):
    version = save_profile(ctx.session, tenant_id=ctx.tenant_id, user_id=ctx.user_id, profile=body,
                           correlation_id=ctx.correlation_id)
    ctx.commit()
    return {"version": version}
