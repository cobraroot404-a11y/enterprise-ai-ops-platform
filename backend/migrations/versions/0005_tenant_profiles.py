"""Tenant profiles: per-tenant domain configuration (see app/profile/schema.py).

Revision ID: 0005

One current profile per tenant (versioned counter; every change is audited with a content hash). Row-level
security like every tenant table. The worker role does not need it (ticketing differences live on the
connector config, which the worker already reads).
"""
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tenant_profiles (
          tenant_id uuid PRIMARY KEY REFERENCES tenants(id),
          version int NOT NULL DEFAULT 1,
          config jsonb NOT NULL,
          updated_by uuid REFERENCES users(id),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        ALTER TABLE tenant_profiles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE tenant_profiles FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tenant_profiles TO eaop_app
          USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
        GRANT SELECT, INSERT, UPDATE ON tenant_profiles TO eaop_app;
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
