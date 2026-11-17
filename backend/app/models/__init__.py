"""SQLAlchemy models mirroring the Alembic schema (the migration is the source of truth)."""
import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    pass


def _uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _created():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _tenant_fk():
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = _created()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True)
    full_name: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String)


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    kind: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String)
    secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = _created()


class TenantProfileRow(Base):
    __tablename__ = "tenant_profiles"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    source_key: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[dt.datetime] = _created()
    # Lifecycle (migration 0009): server-controlled, 'active' or 'deleted'. A deleted document is excluded
    # everywhere at once; the worker then removes its content.
    lifecycle_status: Mapped[str] = mapped_column(String, default="active", server_default="active")
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cleanup_state: Mapped[str | None] = mapped_column(String, nullable=True)  # pending, completed, failed
    cleanup_completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"))
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_backend: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = _created()
    # the chunk generation retrieval uses, and the job that produced it (reprocessing, migration 0010)
    active_generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    processing_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # retained original (0011)


class DocumentSource(Base):
    """Original uploaded bytes (0011): immutable, tenant-scoped, never exposed by the API."""
    __tablename__ = "document_sources"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String)
    parse_options: Mapped[dict] = mapped_column(JSONB, default=dict)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[dt.datetime] = _created()


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"))
    version: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    embedding_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("embedding_profiles.id"))


class EmbeddingProfile(Base):
    __tablename__ = "embedding_profiles"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    provider: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    revision: Mapped[str] = mapped_column(String)
    dim: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = _created()
    activated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestionJob(Base):
    """One upload attempt or reprocessing request (migration 0010); status changes only through app.ingestion.jobs."""
    __tablename__ = "ingestion_jobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    job_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # parsed segments of an upload, only while the job can still run (SQL NULL otherwise)
    payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # retained original (0011)
    connector_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True),
                                                              ForeignKey("connectors.id"), nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("webhook_endpoints.id"),
                                                          nullable=True)  # webhook jobs (0013)
    processing_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    result_chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    from_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    asset_id: Mapped[str] = mapped_column(String)
    asset_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String)
    symptoms: Mapped[list] = mapped_column(JSONB)
    related_incidents: Mapped[list] = mapped_column(JSONB, default=list)
    priority: Mapped[str] = mapped_column(String)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    recommended_action: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String, default="pending_review")
    report_text: Mapped[str] = mapped_column(Text)
    notes: Mapped[list] = mapped_column(JSONB, default=list)
    measurements: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    extraction_backend: Mapped[str] = mapped_column(String)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[dt.datetime] = _created()


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id"))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="DRAFT")
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), server_default=func.gen_random_uuid())
    external_ticket_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), unique=True)
    decision: Mapped[str] = mapped_column(String)
    decided_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    topic: Mapped[str] = mapped_column(String)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = _created()
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(String, default="user")
    action: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = _created()


class ConnectorSyncRecord(Base):
    """Idempotency and provenance of one source record pulled by a connector (migration 0012)."""
    __tablename__ = "connector_sync_records"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    connector_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("connectors.id"),
                                                           nullable=True)
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("webhook_endpoints.id"),
                                                          nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)  # CSV data row
    source_record_id: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String)
    source_version: Mapped[str | None] = mapped_column(String, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    document_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    first_seen_at: Mapped[dt.datetime] = _created()
    last_synced_at: Mapped[dt.datetime] = _created()


class WebhookEndpoint(Base):
    """Inbound webhook endpoint (0013). Holds only the NAMES of environment variables with the signing secrets."""
    __tablename__ = "webhook_endpoints"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String)
    secret_ref: Mapped[str] = mapped_column(String)
    previous_secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = _created()


class WebhookDelivery(Base):
    """Replay ledger: one row per accepted or payload-rejected delivery; UNIQUE (endpoint, delivery id)."""
    __tablename__ = "webhook_deliveries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("webhook_endpoints.id"))
    delivery_id: Mapped[str] = mapped_column(String)
    body_sha256: Mapped[str] = mapped_column(String)
    outcome: Mapped[str] = mapped_column(String)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    received_at: Mapped[dt.datetime] = _created()


class EvaluationRun(Base):
    """Index of an evaluation run (0014): the manifest under evaluation/ is the evidence."""
    __tablename__ = "evaluation_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[str] = mapped_column(String)
    suite: Mapped[str] = mapped_column(String)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    command: Mapped[str | None] = mapped_column(String, nullable=True)
    dataset: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String, nullable=True)
    backends: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    manifest_path: Mapped[str] = mapped_column(String)
    manifest_sha256: Mapped[str] = mapped_column(String)
    recorded_at: Mapped[dt.datetime] = _created()
