"""Controlled storage of original document content (V41-12.03, V41-12.04).

Revision ID: 0011

Additive. New table `document_sources` keeps the bytes of an uploaded file in PostgreSQL (same transaction as the job and the document, covered by the existing backups, protected by
the same row-level security, deleted by the existing cleanup). `ingestion_jobs.source_id` and `document_versions.source_id` are nullable: every document that exists before this
revision has no retained source and stays fully supported (it simply cannot be reprocessed from source).

Row-level security: the application role is tenant isolated; the worker is tenant scoped by policy and may only read, link (document_id, version) and delete sources. Content is
immutable once stored: nobody may UPDATE the bytes, hash or size.

Downgrade refuses while any source exists (the retained original content would be discarded silently); otherwise it restores the previous schema.
"""
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE document_sources (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          document_id uuid REFERENCES documents(id),
          version integer,
          filename text NOT NULL,
          kind text NOT NULL,
          media_type text NOT NULL,
          size_bytes integer NOT NULL,
          content_hash text NOT NULL,
          parse_options jsonb NOT NULL DEFAULT '{}'::jsonb,
          content bytea NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT document_sources_size_matches CHECK (octet_length(content) = size_bytes AND size_bytes > 0 AND size_bytes <= 16777216),
          CONSTRAINT document_sources_hash_shape CHECK (content_hash ~ '^[0-9a-f]{64}$'),
          CONSTRAINT document_sources_link_complete CHECK ((document_id IS NULL) = (version IS NULL))
        )""")
    op.execute("CREATE INDEX document_sources_document_idx ON document_sources (tenant_id, document_id) WHERE document_id IS NOT NULL")
    op.execute("ALTER TABLE document_sources ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_sources FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON document_sources TO eaop_app USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("CREATE POLICY worker_tenant_scoped ON document_sources TO eaop_worker USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("GRANT SELECT, INSERT, DELETE ON document_sources TO eaop_app")
    op.execute("GRANT UPDATE (document_id, version) ON document_sources TO eaop_app, eaop_worker")
    op.execute("GRANT SELECT, DELETE ON document_sources TO eaop_worker")
    op.execute("ALTER TABLE ingestion_jobs ADD COLUMN source_id uuid")
    op.execute("ALTER TABLE document_versions ADD COLUMN source_id uuid")
    op.execute("GRANT UPDATE (source_id) ON document_versions TO eaop_worker")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT count(*) FROM document_sources").scalar():
        raise RuntimeError("refusing to downgrade 0011: retained original document content exists and would be discarded")
    op.execute("ALTER TABLE document_versions DROP COLUMN IF EXISTS source_id")
    op.execute("ALTER TABLE ingestion_jobs DROP COLUMN IF EXISTS source_id")
    op.execute("DROP TABLE IF EXISTS document_sources")
