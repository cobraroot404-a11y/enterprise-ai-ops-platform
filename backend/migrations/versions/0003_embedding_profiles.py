"""Embedding profiles: record which model produced each vector and prevent mixing.

Revision ID: 0003

Each tenant has at most one ACTIVE embedding profile (provider, model, revision, dimension). Every chunk
points at the profile that produced its vector. Retrieval and ingestion only operate on the active
profile, so deterministic test vectors and real model vectors can never be mixed in one index.
Existing chunks (all produced by the deterministic test embedder) are backfilled to that profile.
"""
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE embedding_profiles (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          provider text NOT NULL,
          model text NOT NULL,
          revision text NOT NULL,
          dim int NOT NULL CHECK (dim = 384),
          active boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          activated_at timestamptz,
          UNIQUE (tenant_id, provider, model, revision, dim)
        );
        CREATE UNIQUE INDEX embedding_profiles_one_active ON embedding_profiles (tenant_id) WHERE active;

        ALTER TABLE document_chunks ADD COLUMN embedding_profile_id uuid REFERENCES embedding_profiles(id);

        INSERT INTO embedding_profiles (tenant_id, provider, model, revision, dim, active, activated_at)
        SELECT DISTINCT tenant_id, 'deterministic', 'hashed-bow-test-only', '1', 384, true, now()
        FROM document_chunks;
        UPDATE document_chunks c SET embedding_profile_id = p.id
        FROM embedding_profiles p WHERE p.tenant_id = c.tenant_id AND p.provider = 'deterministic';

        ALTER TABLE document_chunks ALTER COLUMN embedding_profile_id SET NOT NULL;
        CREATE INDEX document_chunks_profile_idx ON document_chunks (tenant_id, embedding_profile_id);

        ALTER TABLE embedding_profiles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE embedding_profiles FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON embedding_profiles TO eaop_app
          USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant());
        GRANT SELECT, INSERT, UPDATE ON embedding_profiles TO eaop_app;
    """)


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
