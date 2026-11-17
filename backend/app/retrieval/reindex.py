"""Atomic re-embedding of a tenant's chunks under a new embedding profile.

Everything happens in the caller's transaction: either every chunk (all versions) is re-embedded and the
new profile is activated, or nothing changes and the old profile stays active. Chunk text, document
provenance (page numbers, record ids), tenant ownership and versions are untouched. The caller commits.
"""
import datetime as dt

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.ai.embeddings import Embedder
from app.audit import service as audit
from app.models import DocumentChunk, DocumentVersion, EmbeddingProfile
from app.retrieval.profiles import _matches, active_profile

BATCH = 64


def _counts(session: Session, tenant_id) -> dict:
    row = session.execute(text(
        "SELECT (SELECT count(*) FROM documents WHERE tenant_id = :t) AS documents, "
        "(SELECT count(*) FROM document_versions WHERE tenant_id = :t) AS versions, "
        "(SELECT count(*) FROM document_chunks WHERE tenant_id = :t) AS chunks, "
        "(SELECT count(*) FROM document_chunks WHERE tenant_id = :t AND is_current) AS current_chunks, "
        "(SELECT count(*) FROM document_chunks WHERE tenant_id = :t AND vector_dims(embedding) = 384) AS dim384"),
        {"t": str(tenant_id)}).one()
    return dict(row._mapping)


def reindex_tenant(session: Session, tenant_id, new_embedder: Embedder, *, actor_id=None) -> dict:
    old = active_profile(session, tenant_id)
    before = _counts(session, tenant_id)
    report = {"tenant_id": str(tenant_id), "to_profile": new_embedder.profile.label(),
              "from_profile": f"{old.provider}:{old.model}@{old.revision}:{old.dim}" if old else None,
              "before": before, "started_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if old is not None and _matches(old, new_embedder):
        report["status"] = "already_active"
        report["after"] = before
        return report

    spec = new_embedder.profile
    new = session.scalar(select(EmbeddingProfile).where(
        EmbeddingProfile.tenant_id == tenant_id, EmbeddingProfile.provider == spec.provider,
        EmbeddingProfile.model == spec.model, EmbeddingProfile.revision == spec.revision,
        EmbeddingProfile.dim == spec.dim))
    if new is None:
        new = EmbeddingProfile(tenant_id=tenant_id, provider=spec.provider, model=spec.model,
                               revision=spec.revision, dim=spec.dim, active=False)
        session.add(new)
        session.flush()

    ids = [r[0] for r in session.execute(select(DocumentChunk.id).where(DocumentChunk.tenant_id == tenant_id)
                                         .order_by(DocumentChunk.id))]
    for start in range(0, len(ids), BATCH):
        batch = ids[start:start + BATCH]
        rows = session.execute(select(DocumentChunk.id, DocumentChunk.text)
                               .where(DocumentChunk.id.in_(batch))).all()
        vectors = new_embedder.embed([r.text for r in rows])
        for row, vector in zip(rows, vectors, strict=True):
            session.execute(update(DocumentChunk).where(DocumentChunk.id == row.id)
                            .values(embedding=vector, embedding_profile_id=new.id))

    if old is not None:
        old.active = False
        session.flush()
    new.active = True
    new.activated_at = dt.datetime.now(dt.timezone.utc)
    session.execute(update(DocumentVersion).where(DocumentVersion.tenant_id == tenant_id)
                    .values(embedding_backend=new_embedder.name))
    session.flush()

    after = _counts(session, tenant_id)
    other = session.scalar(select(func.count()).select_from(DocumentChunk).where(
        DocumentChunk.tenant_id == tenant_id, DocumentChunk.embedding_profile_id != new.id))
    problems = []
    if after["chunks"] != before["chunks"] or after["documents"] != before["documents"]:
        problems.append("document or chunk counts changed")
    if other:
        problems.append(f"{other} chunks are not on the new profile")
    if after["dim384"] != after["chunks"]:
        problems.append("some embeddings do not have 384 dimensions")
    if problems:
        raise RuntimeError("Reindex verification failed, nothing committed: " + "; ".join(problems))
    audit.record(session, tenant_id=tenant_id, actor_id=actor_id, actor_type="user" if actor_id else "system",
                 action="embeddings.reindexed", entity_type="tenant", entity_id=tenant_id,
                 details={"from": report["from_profile"], "to": report["to_profile"],
                          "chunks": after["chunks"]})
    report.update(status="reindexed", after=after, finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
    return report
