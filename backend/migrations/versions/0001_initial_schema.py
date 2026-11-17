"""Initial schema: tenants, identity, documents, retrieval, incidents, tickets, outbox, audit, RLS.

Revision ID: 0001
"""
import os

from alembic import op

revision = "0001"
down_revision = None

EMBEDDING_DIM = 384

TENANT_TABLES = [
    "connectors", "documents", "document_versions", "document_chunks", "incidents",
    "tickets", "approvals", "outbox_events", "audit_events",
]
# Tables the worker role may touch (all tenants), with the privileges it gets.
WORKER_GRANTS = {
    "outbox_events": "SELECT, UPDATE",
    "tickets": "SELECT, UPDATE",
    "approvals": "SELECT",
    "incidents": "SELECT",
    "connectors": "SELECT",
    "audit_events": "SELECT, INSERT",
}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    app_pw = os.environ.get("APP_DB_PASSWORD", "")
    worker_pw = os.environ.get("WORKER_DB_PASSWORD", "")
    if not app_pw or not worker_pw:
        raise RuntimeError("APP_DB_PASSWORD and WORKER_DB_PASSWORD must be set to run migrations")

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    for role in ("eaop_app", "eaop_worker"):
        op.execute(f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
              END IF;
            END $$;""")
    op.execute(f"ALTER ROLE eaop_app PASSWORD {_sql_literal(app_pw)}")
    op.execute(f"ALTER ROLE eaop_worker PASSWORD {_sql_literal(worker_pw)}")

    op.execute("""
        CREATE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;
    """)

    op.execute("""
    CREATE TABLE tenants (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,40}$'),
      name text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      email text NOT NULL UNIQUE,
      full_name text NOT NULL,
      password_hash text NOT NULL,
      is_platform_admin boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE memberships (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      user_id uuid NOT NULL REFERENCES users(id),
      role text NOT NULL CHECK (role IN
        ('tenant_admin','maintenance_supervisor','support_engineer','read_only_auditor')),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, user_id)
    );
    CREATE TABLE connectors (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      kind text NOT NULL CHECK (kind IN ('ticketing','inventory','crm','fleet','rest','csv','webhook')),
      name text NOT NULL,
      base_url text NOT NULL,
      secret_ref text,
      config jsonb NOT NULL DEFAULT '{}',
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, kind, name)
    );
    CREATE TABLE documents (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      source_key text NOT NULL,
      filename text NOT NULL,
      kind text NOT NULL,
      current_version int NOT NULL DEFAULT 1,
      created_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (tenant_id, source_key)
    );
    CREATE TABLE document_versions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      document_id uuid NOT NULL REFERENCES documents(id),
      version int NOT NULL,
      content_hash text NOT NULL,
      size_bytes int NOT NULL,
      media_type text NOT NULL,
      page_count int,
      chunk_count int NOT NULL DEFAULT 0,
      embedding_backend text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (document_id, version),
      UNIQUE (tenant_id, content_hash)
    );
    CREATE TABLE document_chunks (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      document_id uuid NOT NULL REFERENCES documents(id),
      version_id uuid NOT NULL REFERENCES document_versions(id),
      version int NOT NULL,
      chunk_index int NOT NULL,
      text text NOT NULL,
      page_number int,
      record_id text,
      suspicious boolean NOT NULL DEFAULT false,
      is_current boolean NOT NULL DEFAULT true,
      embedding vector(__DIM__) NOT NULL,
      tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
    );
    CREATE INDEX document_chunks_tsv_idx ON document_chunks USING gin (tsv);
    CREATE INDEX document_chunks_embedding_idx ON document_chunks USING hnsw (embedding vector_cosine_ops);
    CREATE INDEX document_chunks_tenant_idx ON document_chunks (tenant_id, is_current);
    CREATE TABLE incidents (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      asset_id text NOT NULL,
      asset_verified boolean NOT NULL DEFAULT false,
      category text NOT NULL,
      symptoms jsonb NOT NULL,
      related_incidents jsonb NOT NULL DEFAULT '[]',
      priority text NOT NULL CHECK (priority IN ('P1','P2','P3','P4')),
      citations jsonb NOT NULL DEFAULT '[]',
      recommended_action text NOT NULL,
      review_status text NOT NULL DEFAULT 'pending_review',
      report_text text NOT NULL,
      notes jsonb NOT NULL DEFAULT '[]',
      extraction_backend text NOT NULL,
      created_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE tickets (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      incident_id uuid NOT NULL REFERENCES incidents(id),
      title text NOT NULL,
      description text NOT NULL,
      priority text NOT NULL CHECK (priority IN ('P1','P2','P3','P4')),
      state text NOT NULL DEFAULT 'DRAFT' CHECK (state IN
        ('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','SUBMITTING','SUBMITTED',
         'FAILED','RETRY_PENDING','CANCELLED')),
      idempotency_key uuid NOT NULL DEFAULT gen_random_uuid(),
      external_ticket_id text,
      attempts int NOT NULL DEFAULT 0,
      last_error text,
      created_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      submitted_at timestamptz
    );
    CREATE UNIQUE INDEX tickets_one_live_per_incident
      ON tickets (tenant_id, incident_id) WHERE state NOT IN ('CANCELLED','REJECTED');
    CREATE TABLE approvals (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      ticket_id uuid NOT NULL REFERENCES tickets(id) UNIQUE,
      decision text NOT NULL CHECK (decision IN ('approved','rejected')),
      decided_by uuid NOT NULL REFERENCES users(id),
      comment text,
      requested_at timestamptz,
      decided_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE TABLE outbox_events (
      id bigserial PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants(id),
      topic text NOT NULL,
      aggregate_id uuid NOT NULL,
      payload jsonb NOT NULL DEFAULT '{}',
      status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','done','dead')),
      attempts int NOT NULL DEFAULT 0,
      available_at timestamptz NOT NULL DEFAULT now(),
      locked_until timestamptz,
      last_error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      processed_at timestamptz
    );
    CREATE UNIQUE INDEX outbox_one_active_per_aggregate
      ON outbox_events (topic, aggregate_id) WHERE status IN ('pending','processing');
    CREATE TABLE audit_events (
      id bigserial PRIMARY KEY,
      tenant_id uuid REFERENCES tenants(id),
      actor_id uuid,
      actor_type text NOT NULL DEFAULT 'user',
      action text NOT NULL,
      entity_type text NOT NULL,
      entity_id text,
      details jsonb NOT NULL DEFAULT '{}',
      correlation_id text,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX audit_events_tenant_idx ON audit_events (tenant_id, id DESC);
    """.replace("__DIM__", str(EMBEDDING_DIM)))

    # Audit log is append-only for every role, including the owner.
    op.execute("""
    CREATE FUNCTION audit_events_immutable() RETURNS trigger LANGUAGE plpgsql AS
    $$ BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$;
    CREATE TRIGGER audit_events_no_update BEFORE UPDATE OR DELETE ON audit_events
      FOR EACH ROW EXECUTE FUNCTION audit_events_immutable();
    """)

    # Row-level security: tenant data is invisible unless app.tenant_id is set in the transaction.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} TO eaop_app "
            "USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
        )
    for table in WORKER_GRANTS:
        op.execute(f"CREATE POLICY worker_access ON {table} TO eaop_worker USING (true) WITH CHECK (true)")

    op.execute("GRANT USAGE ON SCHEMA public TO eaop_app, eaop_worker")
    op.execute("GRANT SELECT, INSERT, UPDATE ON tenants, users, memberships TO eaop_app")
    for table in TENANT_TABLES:
        privs = "SELECT, INSERT" if table == "audit_events" else "SELECT, INSERT, UPDATE, DELETE"
        op.execute(f"GRANT {privs} ON {table} TO eaop_app")
    for table, privs in WORKER_GRANTS.items():
        op.execute(f"GRANT {privs} ON {table} TO eaop_worker")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO eaop_app, eaop_worker")
    op.execute("GRANT EXECUTE ON FUNCTION app_current_tenant() TO eaop_app, eaop_worker")


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for the initial schema")
