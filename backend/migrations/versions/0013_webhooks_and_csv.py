"""Signed inbound webhooks and CSV provenance (V41-12.01 webhook part, V41-11.01).

Revision ID: 0013

Additive.
* `webhook_endpoints`: one row per endpoint an authorised tenant administrator provisions. The row stores only the NAMES of environment variables that hold the HMAC signing secrets (current
  and, during a rotation, previous), never a secret. Row-level security isolates tenants for the application role.
* `webhook_endpoint_lookup(uuid)`: a narrowly scoped SECURITY DEFINER function. A delivery arrives without any user token, so the receiver must find the tenant from the unguessable endpoint id
  BEFORE a tenant context exists. The function takes exactly one endpoint id and returns the tenant, the secret reference names, the status and the configuration; it exposes nothing else and
  cannot enumerate. The tenant identity therefore comes only from trusted server-side configuration, never from the request.
* `webhook_deliveries`: the durable replay ledger. UNIQUE (endpoint, delivery id) makes replay detection atomic: the insert that wins accepts the delivery, every other attempt is a replay.
* `ingestion_jobs`: job type `webhook`, `endpoint_id`. `connector_sync_records` also serves endpoints (connector_id becomes optional, exactly one of connector or endpoint is set), and gains
  `source_row` (CSV row provenance).
Downgrade refuses while any endpoint, delivery or webhook job exists.
"""
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE webhook_endpoints (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          name text NOT NULL,
          secret_ref text NOT NULL,
          previous_secret_ref text,
          status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
          config jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_by uuid,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT webhook_endpoints_name_unique UNIQUE (tenant_id, name),
          CONSTRAINT webhook_endpoints_secret_ref_shape CHECK (secret_ref ~ '^[A-Z][A-Z0-9_]{2,60}$'),
          CONSTRAINT webhook_endpoints_previous_shape CHECK (previous_secret_ref IS NULL OR (previous_secret_ref ~ '^[A-Z][A-Z0-9_]{2,60}$' AND previous_secret_ref <> secret_ref))
        )""")
    # ENABLE (not FORCE): the table owner, which the lookup function runs as, is the only role that sees across tenants, and only through that function
    op.execute("ALTER TABLE webhook_endpoints ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON webhook_endpoints TO eaop_app USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("CREATE POLICY worker_tenant_scoped ON webhook_endpoints TO eaop_worker USING (tenant_id = app_current_tenant())")
    op.execute("GRANT SELECT, INSERT ON webhook_endpoints TO eaop_app")
    op.execute("GRANT UPDATE (secret_ref, previous_secret_ref, status, updated_at) ON webhook_endpoints TO eaop_app")
    op.execute("GRANT SELECT ON webhook_endpoints TO eaop_worker")
    op.execute("""
        CREATE FUNCTION webhook_endpoint_lookup(p_endpoint uuid)
          RETURNS TABLE (tenant_id uuid, secret_ref text, previous_secret_ref text, status text, config jsonb, name text)
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
        $$ SELECT w.tenant_id, w.secret_ref, w.previous_secret_ref, w.status, w.config, w.name FROM webhook_endpoints w WHERE w.id = p_endpoint $$;
        REVOKE EXECUTE ON FUNCTION webhook_endpoint_lookup(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION webhook_endpoint_lookup(uuid) TO eaop_app;
    """)
    op.execute("""
        CREATE TABLE webhook_deliveries (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          endpoint_id uuid NOT NULL REFERENCES webhook_endpoints(id),
          delivery_id text NOT NULL,
          body_sha256 text NOT NULL,
          outcome text NOT NULL CHECK (outcome IN ('accepted', 'rejected_invalid_payload')),
          job_id uuid,
          received_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT webhook_deliveries_replay_key UNIQUE (endpoint_id, delivery_id),
          CONSTRAINT webhook_deliveries_delivery_id_shape CHECK (delivery_id ~ '^[A-Za-z0-9._:\\-]{8,64}$'),
          CONSTRAINT webhook_deliveries_hash_shape CHECK (body_sha256 ~ '^[0-9a-f]{64}$')
        )""")
    op.execute("CREATE INDEX webhook_deliveries_received_idx ON webhook_deliveries (tenant_id, received_at DESC)")
    op.execute("ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE webhook_deliveries FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON webhook_deliveries TO eaop_app USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("GRANT SELECT, INSERT ON webhook_deliveries TO eaop_app")  # append-only for the application: a delivery row is never edited or deleted
    op.execute("GRANT SELECT ON webhook_deliveries TO eaop_worker")
    op.execute("CREATE POLICY worker_tenant_scoped ON webhook_deliveries TO eaop_worker USING (tenant_id = app_current_tenant())")
    # jobs: type webhook
    op.execute("ALTER TABLE ingestion_jobs DROP CONSTRAINT ingestion_jobs_job_type_check")
    op.execute("ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_job_type_check CHECK (job_type IN ('ingest', 'reprocess', 'sync', 'webhook'))")
    op.execute("ALTER TABLE ingestion_jobs ADD COLUMN endpoint_id uuid REFERENCES webhook_endpoints(id)")
    op.execute("ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_webhook_has_endpoint CHECK ((job_type = 'webhook') = (endpoint_id IS NOT NULL))")
    # sync records serve endpoints too
    op.execute("ALTER TABLE connector_sync_records ADD COLUMN endpoint_id uuid REFERENCES webhook_endpoints(id)")
    op.execute("ALTER TABLE connector_sync_records ADD COLUMN source_row integer")
    op.execute("ALTER TABLE connector_sync_records ALTER COLUMN connector_id DROP NOT NULL")
    op.execute("ALTER TABLE connector_sync_records DROP CONSTRAINT connector_sync_records_key")
    op.execute("ALTER TABLE connector_sync_records ADD CONSTRAINT connector_sync_records_one_origin CHECK ((connector_id IS NULL) <> (endpoint_id IS NULL))")
    op.execute("CREATE UNIQUE INDEX connector_sync_records_connector_key ON connector_sync_records (tenant_id, connector_id, source_record_id) WHERE connector_id IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX connector_sync_records_endpoint_key ON connector_sync_records (tenant_id, endpoint_id, source_record_id) WHERE endpoint_id IS NOT NULL")
    op.execute("GRANT UPDATE (source_row) ON connector_sync_records TO eaop_worker")  # (the worker already holds table-level UPDATE; stated for clarity)


def downgrade() -> None:
    bind = op.get_bind()
    if (bind.exec_driver_sql("SELECT count(*) FROM webhook_endpoints").scalar() or bind.exec_driver_sql("SELECT count(*) FROM webhook_deliveries").scalar()
            or bind.exec_driver_sql("SELECT count(*) FROM ingestion_jobs WHERE job_type = 'webhook'").scalar()
            or bind.exec_driver_sql("SELECT count(*) FROM connector_sync_records WHERE endpoint_id IS NOT NULL").scalar()):
        raise RuntimeError("refusing to downgrade 0013: webhook endpoints, deliveries or webhook-sourced records exist and their provenance would be discarded")
    op.execute("DROP INDEX IF EXISTS connector_sync_records_endpoint_key")
    op.execute("DROP INDEX IF EXISTS connector_sync_records_connector_key")
    op.execute("ALTER TABLE connector_sync_records DROP CONSTRAINT IF EXISTS connector_sync_records_one_origin")
    op.execute("ALTER TABLE connector_sync_records ADD CONSTRAINT connector_sync_records_key UNIQUE (tenant_id, connector_id, source_record_id)")
    op.execute("ALTER TABLE connector_sync_records ALTER COLUMN connector_id SET NOT NULL")
    op.execute("ALTER TABLE connector_sync_records DROP COLUMN IF EXISTS source_row")
    op.execute("ALTER TABLE connector_sync_records DROP COLUMN IF EXISTS endpoint_id")
    op.execute("ALTER TABLE ingestion_jobs DROP CONSTRAINT IF EXISTS ingestion_jobs_webhook_has_endpoint")
    op.execute("ALTER TABLE ingestion_jobs DROP COLUMN IF EXISTS endpoint_id")
    op.execute("ALTER TABLE ingestion_jobs DROP CONSTRAINT ingestion_jobs_job_type_check")
    op.execute("ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_job_type_check CHECK (job_type IN ('ingest', 'reprocess', 'sync'))")
    op.execute("DROP TABLE IF EXISTS webhook_deliveries")
    op.execute("DROP FUNCTION IF EXISTS webhook_endpoint_lookup(uuid)")
    op.execute("DROP TABLE IF EXISTS webhook_endpoints")
