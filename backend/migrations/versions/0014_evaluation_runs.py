"""Evaluation runs registry (V41-17.04 entity "Evaluation runs").

Revision ID: 0014

Additive. `evaluation_runs` records WHICH evaluation runs exist: run id, suite, command, dataset, timestamps, backend summary, the path of the run's manifest and the SHA-256 of that manifest.
The manifests and reports under `evaluation/` remain the evidence and the only source of the measurements; this table is an index with a tamper check (a manifest that changes after it
was registered is reported, never silently re-registered). It holds no tenant data, so like `tenants` it is not under row-level security; the application and worker roles may only read it,
the database owner (the indexing script, `scripts/index_evaluation_runs.py`) writes it. Downgrade refuses while rows exist.
"""
from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE evaluation_runs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id text NOT NULL,
          suite text NOT NULL,
          label text,
          command text,
          dataset text,
          started_at timestamptz,
          finished_at timestamptz,
          duration_s double precision,
          git_commit text,
          backends jsonb,
          manifest_path text NOT NULL UNIQUE,
          manifest_sha256 text NOT NULL,
          recorded_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT evaluation_runs_sha_shape CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$')
        )""")
    op.execute("CREATE INDEX evaluation_runs_suite_idx ON evaluation_runs (suite, started_at DESC)")
    op.execute("GRANT SELECT ON evaluation_runs TO eaop_app, eaop_worker")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT count(*) FROM evaluation_runs").scalar():
        raise RuntimeError("refusing to downgrade 0014: the evaluation run registry holds rows (it can be rebuilt with scripts/index_evaluation_runs.py, but delete the rows deliberately first)")
    op.execute("DROP TABLE IF EXISTS evaluation_runs")
