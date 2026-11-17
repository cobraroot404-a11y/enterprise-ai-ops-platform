"""Shared concurrency limits (leases) for the CPU-bound endpoints.

Revision ID: 0016

Additive; existing PostgreSQL only. `concurrency_leases` holds one row per in-flight holder of a named slot pool (for example `inference`, `ingestion`). It is reached only through SECURITY
DEFINER functions: `concurrency_acquire(key, limit, ttl_seconds)` takes a transaction-scoped advisory lock on the key, deletes that key's expired leases, counts the live ones and inserts a
lease only if fewer than `limit` exist, so any number of API processes share one limit and two callers can never both take the last slot. A holder that crashes frees its slot when its
lease expires (the ttl); a normal holder releases it with `concurrency_release`. No tenant data is stored. Downgrade drops the table (leases are ephemeral).
"""
from alembic import op

revision = "0016"
down_revision = "0015"

FUNCTIONS = ["concurrency_acquire(text, integer, integer)", "concurrency_release(uuid)"]


def upgrade() -> None:
    op.execute("""
        CREATE TABLE concurrency_leases (
          lease_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          slot_key text NOT NULL CHECK (length(slot_key) BETWEEN 1 AND 100),
          expires_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )""")
    op.execute("CREATE INDEX concurrency_leases_key_idx ON concurrency_leases (slot_key, expires_at)")
    op.execute("""
        CREATE FUNCTION concurrency_acquire(p_key text, p_limit integer, p_ttl_seconds integer)
          RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE v_id uuid; v_live integer;
        BEGIN
          IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 100 OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 OR p_ttl_seconds IS NULL OR p_ttl_seconds NOT BETWEEN 1 AND 3600 THEN
            RAISE EXCEPTION 'invalid concurrency arguments' USING ERRCODE = '22023';
          END IF;
          PERFORM pg_advisory_xact_lock(hashtext('eaop-concurrency:' || p_key));
          DELETE FROM concurrency_leases WHERE slot_key = p_key AND expires_at <= clock_timestamp();
          SELECT count(*) INTO v_live FROM concurrency_leases WHERE slot_key = p_key;
          IF v_live >= p_limit THEN RETURN NULL; END IF;
          INSERT INTO concurrency_leases (slot_key, expires_at) VALUES (p_key, clock_timestamp() + make_interval(secs => p_ttl_seconds)) RETURNING lease_id INTO v_id;
          RETURN v_id;
        END $$""")
    op.execute("""
        CREATE FUNCTION concurrency_release(p_lease uuid) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS
        $$ DELETE FROM concurrency_leases WHERE lease_id = p_lease $$""")
    for fn in FUNCTIONS:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn} TO eaop_app, eaop_worker")


def downgrade() -> None:
    for fn in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")
    op.execute("DROP TABLE IF EXISTS concurrency_leases")
