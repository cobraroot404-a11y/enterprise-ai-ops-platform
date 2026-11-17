"""Narrow lookup used by the egress policy: the slug of a connector's tenant.

Revision ID: 0006

The outbound allow-list is scoped per tenant slug. The worker role has no access to `tenants`, so it gets this
single-purpose SECURITY DEFINER function (returns only the slug for a given tenant id) instead of table access.
"""
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION connector_tenant_slug(p_tenant uuid) RETURNS text LANGUAGE sql STABLE SECURITY DEFINER
          SET search_path = public, pg_temp AS
        $$ SELECT slug FROM tenants WHERE id = p_tenant $$;
        REVOKE EXECUTE ON FUNCTION connector_tenant_slug(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION connector_tenant_slug(uuid) TO eaop_app, eaop_worker;
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
