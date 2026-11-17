"""Per-tenant active embedding profile: guards against mixing or mismatching embedding models."""
import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.embeddings import Embedder
from app.core.errors import AppError
from app.models import DocumentChunk, EmbeddingProfile


class IncompatibleEmbeddingModel(AppError):
    status_code = 409
    code = "embedding_model_mismatch"


def active_profile(session: Session, tenant_id) -> EmbeddingProfile | None:
    return session.scalar(select(EmbeddingProfile).where(EmbeddingProfile.tenant_id == tenant_id,
                                                         EmbeddingProfile.active.is_(True)))


def _matches(profile: EmbeddingProfile, embedder: Embedder) -> bool:
    spec = embedder.profile
    return (profile.provider, profile.model, profile.revision, profile.dim) == (
        spec.provider, spec.model, spec.revision, spec.dim)


def require_compatible(session: Session, tenant_id, embedder: Embedder) -> EmbeddingProfile | None:
    """Return the tenant's active profile, raising if it differs from the configured embedder.

    A tenant with no profile and no chunks has nothing to mismatch (returns None)."""
    profile = active_profile(session, tenant_id)
    if profile is None:
        if session.scalar(select(func.count()).select_from(DocumentChunk)
                          .where(DocumentChunk.tenant_id == tenant_id)):
            raise IncompatibleEmbeddingModel("Tenant has chunks but no active embedding profile",
                                             code="embedding_profile_missing")
        return None
    if not _matches(profile, embedder):
        raise IncompatibleEmbeddingModel(
            f"Tenant index uses '{profile.provider}:{profile.model}@{profile.revision}' but the configured "
            f"embedder is '{embedder.profile.label()}'. Run scripts/reindex_embeddings.py for this tenant.")
    return profile


def ensure_active_profile(session: Session, tenant_id, embedder: Embedder) -> EmbeddingProfile:
    """Profile that new vectors must be written under (creating the first one for a fresh tenant)."""
    profile = require_compatible(session, tenant_id, embedder)
    if profile is not None:
        return profile
    spec = embedder.profile
    profile = EmbeddingProfile(tenant_id=tenant_id, provider=spec.provider, model=spec.model,
                               revision=spec.revision, dim=spec.dim, active=True,
                               activated_at=dt.datetime.now(dt.timezone.utc))
    session.add(profile)
    session.flush()
    return profile
