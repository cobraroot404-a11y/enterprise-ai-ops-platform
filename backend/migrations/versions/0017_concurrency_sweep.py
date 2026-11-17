"""Housekeeping for concurrency leases.

Revision ID: 0017

Additive. `concurrency_acquire` (0016) removes expired leases only for the key it is called with, so leases of a key that is never requested again (for example a per-tenant share key of
a tenant that stopped sending requests after a crash) would stay in the table. `concurrency_sweep()` deletes every expired lease, in bounded batches, and is called periodically by the
worker together with `rate_limit_sweep` (0015). It never removes a live lease. Downgrade drops only the function.
"""
from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION concurrency_sweep() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE n integer;
        BEGIN
          WITH doomed AS (SELECT lease_id FROM concurrency_leases WHERE expires_at <= clock_timestamp() ORDER BY expires_at LIMIT 1000 FOR UPDATE SKIP LOCKED)
          DELETE FROM concurrency_leases l USING doomed d WHERE l.lease_id = d.lease_id;
          GET DIAGNOSTICS n = ROW_COUNT;
          RETURN n;
        END $$""")
    op.execute("REVOKE EXECUTE ON FUNCTION concurrency_sweep() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION concurrency_sweep() TO eaop_app, eaop_worker")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS concurrency_sweep()")
