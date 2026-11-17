"""Row-level security for memberships (least privilege).

Revision ID: 0002

Policies for the API role:
  * SELECT: rows of the current tenant, or the caller's own memberships (needed to sign in and to
    discover which tenants a user belongs to).
  * INSERT/UPDATE/DELETE: only inside the current tenant context AND never on the caller's own row,
    so nobody can self-assign or escalate their own role. A user context must be present.
Platform administration works by setting the tenant context of the tenant being administered.
"""
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;
        GRANT EXECUTE ON FUNCTION app_current_user() TO eaop_app, eaop_worker;
        GRANT DELETE ON memberships TO eaop_app;

        ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
        ALTER TABLE memberships FORCE ROW LEVEL SECURITY;

        CREATE POLICY membership_select ON memberships FOR SELECT TO eaop_app
          USING (tenant_id = app_current_tenant() OR user_id = app_current_user());
        CREATE POLICY membership_insert ON memberships FOR INSERT TO eaop_app
          WITH CHECK (tenant_id = app_current_tenant() AND app_current_user() IS NOT NULL
                      AND user_id <> app_current_user());
        CREATE POLICY membership_update ON memberships FOR UPDATE TO eaop_app
          USING (tenant_id = app_current_tenant() AND app_current_user() IS NOT NULL
                 AND user_id <> app_current_user())
          WITH CHECK (tenant_id = app_current_tenant() AND app_current_user() IS NOT NULL
                      AND user_id <> app_current_user());
        CREATE POLICY membership_delete ON memberships FOR DELETE TO eaop_app
          USING (tenant_id = app_current_tenant() AND app_current_user() IS NOT NULL
                 AND user_id <> app_current_user());
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
