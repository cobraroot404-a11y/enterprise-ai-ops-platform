"""REST pull synchronization (V41-12.01 REST part, V41-11.01, V41-11.02).

Revision ID: 0012

Additive. The existing `ingestion_jobs` table gains a third job type, `sync` (a pull of records from a tenant's REST connector), a `connector_id` and a `progress` document (where the
pager is and the counts, saved after every page so a retry resumes). The new table `connector_sync_records` holds one row per (tenant, connector, source record id): the content hash and
version marker last ingested, the document and version created from it, the job that did it, and whether the document was deleted since. That row is the idempotency and provenance record:
an unchanged record is skipped, a changed one becomes a new version, a user-deleted one stays deleted until its content changes.

Row-level security: tenant isolation for the application role, and a tenant-scoped policy for the worker (it writes these rows, and the retained originals of pulled records, only inside the tenant context of the job it is running; the worker therefore also receives INSERT on document_sources, which 0011 withheld because uploads were stored by the API).
Downgrade refuses while any sync job or sync record exists (the provenance would be discarded).
"""
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.execute("ALTER TABLE ingestion_jobs DROP CONSTRAINT ingestion_jobs_job_type_check")
    op.execute("ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_job_type_check CHECK (job_type IN ('ingest', 'reprocess', 'sync'))")
    op.execute("ALTER TABLE ingestion_jobs ADD COLUMN connector_id uuid REFERENCES connectors(id)")
    op.execute("ALTER TABLE ingestion_jobs ADD COLUMN progress jsonb")
    op.execute("ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_sync_has_connector CHECK ((job_type = 'sync') = (connector_id IS NOT NULL))")
    op.execute("CREATE INDEX ingestion_jobs_connector_idx ON ingestion_jobs (tenant_id, connector_id) WHERE connector_id IS NOT NULL")
    op.execute("""
        CREATE TABLE connector_sync_records (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          connector_id uuid NOT NULL REFERENCES connectors(id),
          source_record_id text NOT NULL,
          content_hash text NOT NULL,
          source_version text,
          document_id uuid REFERENCES documents(id),
          document_version integer,
          last_job_id uuid,
          status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
          first_seen_at timestamptz NOT NULL DEFAULT now(),
          last_synced_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT connector_sync_records_hash_shape CHECK (content_hash ~ '^[0-9a-f]{64}$'),
          CONSTRAINT connector_sync_records_key UNIQUE (tenant_id, connector_id, source_record_id)
        )""")
    op.execute("CREATE INDEX connector_sync_records_document_idx ON connector_sync_records (tenant_id, document_id) WHERE document_id IS NOT NULL")
    op.execute("ALTER TABLE connector_sync_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE connector_sync_records FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON connector_sync_records TO eaop_app USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("CREATE POLICY worker_tenant_scoped ON connector_sync_records TO eaop_worker USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("GRANT SELECT ON connector_sync_records TO eaop_app")
    op.execute("GRANT UPDATE (status) ON connector_sync_records TO eaop_app")  # the deletion of a document marks its sync record deleted (application session)
    op.execute("GRANT SELECT, INSERT, UPDATE ON connector_sync_records TO eaop_worker")
    op.execute("GRANT INSERT ON document_sources TO eaop_worker")  # a sync job stores the original of each pulled record (still only inside the job tenant context, by policy)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT count(*) FROM connector_sync_records").scalar() or bind.exec_driver_sql("SELECT count(*) FROM ingestion_jobs WHERE job_type = 'sync'").scalar():
        raise RuntimeError("refusing to downgrade 0012: REST synchronization jobs or records exist and their provenance would be discarded")
    op.execute("REVOKE INSERT ON document_sources FROM eaop_worker")
    op.execute("DROP TABLE IF EXISTS connector_sync_records")
    op.execute("DROP INDEX IF EXISTS ingestion_jobs_connector_idx")
    op.execute("ALTER TABLE ingestion_jobs DROP CONSTRAINT IF EXISTS ingestion_jobs_sync_has_connector")
    op.execute("ALTER TABLE ingestion_jobs DROP COLUMN IF EXISTS progress")
    op.execute("ALTER TABLE ingestion_jobs DROP COLUMN IF EXISTS connector_id")
    op.execute("ALTER TABLE ingestion_jobs DROP CONSTRAINT ingestion_jobs_job_type_check")
    op.execute("ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_job_type_check CHECK (job_type IN ('ingest', 'reprocess'))")
