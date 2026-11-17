"""Durable ingestion jobs, bounded retry and safe reprocessing (V41-12.03, V41-12.04).

Revision ID: 0010

Additive. New table `ingestion_jobs` (one row per upload attempt or reprocessing request) with a server-controlled state machine
(QUEUED, PROCESSING, RETRY_PENDING, COMPLETED, FAILED, CANCELLED), attempt and retry bookkeeping, a fencing lease (claim_token, locked_until) so a stale worker cannot overwrite
newer state, a sanitised error code, and a partial unique index so a duplicate submission of the same work while one is active resolves to the existing job.
`document_chunks.generation` and `document_versions.active_generation` (both default 1, so every existing row is unchanged) let a reprocessing attempt build a replacement set of chunks
that stays invisible to retrieval until it is validated and activated; retired generations are kept (not current), so historical citations keep their meaning.

Row-level security: tenant isolation for the application role (as every tenant table); the worker may see all jobs (it claims across tenants, exactly like outbox_events) but
does all document work inside a tenant-scoped session. To store processed content the worker receives INSERT and column-limited UPDATE on the document tables and
embedding_profiles, each under a policy `tenant_id = app_current_tenant()` (added for embedding_profiles here, for the document tables in 0009).

Downgrade refuses while any job exists or any chunk generation above 1 exists (the lineage evidence would be lost); otherwise it restores the previous schema.
"""
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("ALTER TABLE document_chunks ADD COLUMN generation integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE document_versions ADD COLUMN active_generation integer NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE document_versions ADD COLUMN processing_job_id uuid")
    op.execute("""
        CREATE TABLE ingestion_jobs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          job_type text NOT NULL CHECK (job_type IN ('ingest', 'reprocess')),
          status text NOT NULL CHECK (status IN ('QUEUED', 'PROCESSING', 'RETRY_PENDING', 'COMPLETED', 'FAILED', 'CANCELLED')),
          document_id uuid REFERENCES documents(id),
          source_version integer,
          filename text,
          kind text,
          attempts integer NOT NULL DEFAULT 0,
          max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
          next_attempt_at timestamptz NOT NULL DEFAULT now(),
          claim_token uuid,
          locked_until timestamptz,
          claimed_by text,
          error_code text,
          error_detail text,
          idempotency_key text,
          requested_by uuid,
          correlation_id text,
          payload jsonb,
          processing_config jsonb NOT NULL DEFAULT '{}'::jsonb,
          outcome text,
          result_chunks integer,
          from_generation integer,
          to_generation integer,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CONSTRAINT ingestion_jobs_attempts_bounded CHECK (attempts >= 0 AND attempts <= max_attempts),
          CONSTRAINT ingestion_jobs_terminal_time CHECK ((status IN ('COMPLETED', 'FAILED', 'CANCELLED')) = (completed_at IS NOT NULL)),
          CONSTRAINT ingestion_jobs_payload_only_while_runnable CHECK (payload IS NULL OR status IN ('QUEUED', 'PROCESSING', 'RETRY_PENDING')),
          CONSTRAINT ingestion_jobs_lease_while_processing CHECK ((status = 'PROCESSING') = (claim_token IS NOT NULL AND locked_until IS NOT NULL))
        )""")
    op.execute("CREATE INDEX ingestion_jobs_tenant_created_idx ON ingestion_jobs (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX ingestion_jobs_document_idx ON ingestion_jobs (document_id) WHERE document_id IS NOT NULL")
    op.execute("CREATE INDEX ingestion_jobs_due_idx ON ingestion_jobs (next_attempt_at) WHERE status IN ('QUEUED', 'RETRY_PENDING')")
    op.execute("CREATE INDEX ingestion_jobs_lease_idx ON ingestion_jobs (locked_until) WHERE status = 'PROCESSING'")
    op.execute("CREATE UNIQUE INDEX ingestion_jobs_active_key ON ingestion_jobs (tenant_id, idempotency_key) "
               "WHERE idempotency_key IS NOT NULL AND status IN ('QUEUED', 'PROCESSING', 'RETRY_PENDING')")
    op.execute("ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON ingestion_jobs TO eaop_app USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("CREATE POLICY worker_access ON ingestion_jobs TO eaop_worker USING (true) WITH CHECK (true)")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ingestion_jobs TO eaop_app")
    op.execute("GRANT SELECT, UPDATE ON ingestion_jobs TO eaop_worker")
    # What the worker needs to STORE processed content, tenant-scoped by policy and column-limited:
    op.execute("CREATE POLICY worker_tenant_scoped ON embedding_profiles TO eaop_worker USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("GRANT SELECT, INSERT ON embedding_profiles TO eaop_worker")
    op.execute("GRANT INSERT ON documents TO eaop_worker")
    op.execute("GRANT UPDATE (current_version, kind) ON documents TO eaop_worker")
    op.execute("GRANT INSERT ON document_versions TO eaop_worker")
    op.execute("GRANT UPDATE (active_generation, processing_job_id, embedding_backend, chunk_count) ON document_versions TO eaop_worker")
    op.execute("GRANT INSERT ON document_chunks TO eaop_worker")
    op.execute("GRANT UPDATE (is_current) ON document_chunks TO eaop_worker")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT count(*) FROM ingestion_jobs").scalar() or bind.exec_driver_sql("SELECT count(*) FROM document_chunks WHERE generation > 1").scalar():
        raise RuntimeError("refusing to downgrade 0010: ingestion jobs or reprocessed chunk generations exist and their lineage evidence would be discarded")
    op.execute("REVOKE UPDATE (is_current) ON document_chunks FROM eaop_worker")
    op.execute("REVOKE INSERT ON document_chunks FROM eaop_worker")
    op.execute("REVOKE UPDATE (active_generation, processing_job_id, embedding_backend, chunk_count) ON document_versions FROM eaop_worker")
    op.execute("REVOKE INSERT ON document_versions FROM eaop_worker")
    op.execute("REVOKE UPDATE (current_version, kind) ON documents FROM eaop_worker")
    op.execute("REVOKE INSERT ON documents FROM eaop_worker")
    op.execute("REVOKE SELECT, INSERT ON embedding_profiles FROM eaop_worker")
    op.execute("DROP POLICY IF EXISTS worker_tenant_scoped ON embedding_profiles")
    op.execute("DROP TABLE IF EXISTS ingestion_jobs")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS processing_job_id")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS active_generation")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS generation")
