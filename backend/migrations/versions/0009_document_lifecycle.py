"""Document lifecycle: audited logical deletion with reliable content cleanup (V41-12.05).

Revision ID: 0009

Additive and minimal. `documents` gains the server-controlled lifecycle:
  lifecycle_status     'active' (default for every existing row, so nothing existing changes) | 'deleted'
  deleted_at           when the deletion was requested
  deleted_by           the authorised actor
  cleanup_state        NULL while active; 'pending' -> 'completed' | 'failed' once deleted
  cleanup_completed_at set only when the cleanup was verified
A CHECK constraint ties the columns together (an active document carries no deletion data; a deleted one always has a time and a cleanup state).

The cleanup runs in the outbox worker (role eaop_worker), which previously had no access to document tables. It gets exactly what cleanup needs, and tenant-scoped:
  documents: SELECT and UPDATE of cleanup_state / cleanup_completed_at only
  document_chunks, document_versions: SELECT, DELETE
  incidents: UPDATE of citations and related_incidents only (to redact quotes copied from the deleted document); the existing worker policy on incidents is unchanged
  new policies on documents, document_chunks and document_versions for eaop_worker are `tenant_id = app_current_tenant()`: unlike its older tables, the worker can NOT see
  another tenant's document artifacts at all; the cleanup sets the tenant context from the outbox event before touching anything.

Downgrade refuses to run while any document is in the deleted state (it would discard lifecycle evidence); otherwise it removes the policies, grants and columns.
"""
from alembic import op

revision = "0009"
down_revision = "0008"

WORKER_TABLES = ("documents", "document_chunks", "document_versions")


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN lifecycle_status text NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE documents ADD COLUMN deleted_at timestamptz")
    op.execute("ALTER TABLE documents ADD COLUMN deleted_by uuid")
    op.execute("ALTER TABLE documents ADD COLUMN cleanup_state text")
    op.execute("ALTER TABLE documents ADD COLUMN cleanup_completed_at timestamptz")
    op.execute("ALTER TABLE documents ADD CONSTRAINT documents_lifecycle_status_check CHECK (lifecycle_status IN ('active', 'deleted'))")
    op.execute("ALTER TABLE documents ADD CONSTRAINT documents_cleanup_state_check CHECK (cleanup_state IS NULL OR cleanup_state IN ('pending', 'completed', 'failed'))")
    op.execute(
        "ALTER TABLE documents ADD CONSTRAINT documents_lifecycle_consistent CHECK ("
        "(lifecycle_status = 'active' AND deleted_at IS NULL AND deleted_by IS NULL AND cleanup_state IS NULL AND cleanup_completed_at IS NULL) OR "
        "(lifecycle_status = 'deleted' AND deleted_at IS NOT NULL AND cleanup_state IS NOT NULL "
        "AND ((cleanup_state = 'completed') = (cleanup_completed_at IS NOT NULL))))")
    for table in WORKER_TABLES:
        op.execute(f"CREATE POLICY worker_tenant_scoped ON {table} TO eaop_worker USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())")
    op.execute("GRANT SELECT ON documents TO eaop_worker")
    op.execute("GRANT UPDATE (cleanup_state, cleanup_completed_at) ON documents TO eaop_worker")
    op.execute("GRANT SELECT, DELETE ON document_chunks, document_versions TO eaop_worker")
    op.execute("GRANT UPDATE (citations, related_incidents) ON incidents TO eaop_worker")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT count(*) FROM documents WHERE lifecycle_status = 'deleted'").scalar():
        raise RuntimeError("refusing to downgrade 0009: deleted documents exist and their lifecycle evidence would be discarded")
    op.execute("REVOKE UPDATE (citations, related_incidents) ON incidents FROM eaop_worker")
    op.execute("REVOKE SELECT, DELETE ON document_chunks, document_versions FROM eaop_worker")
    op.execute("REVOKE UPDATE (cleanup_state, cleanup_completed_at) ON documents FROM eaop_worker")
    op.execute("REVOKE SELECT ON documents FROM eaop_worker")
    for table in WORKER_TABLES:
        op.execute(f"DROP POLICY IF EXISTS worker_tenant_scoped ON {table}")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_lifecycle_consistent")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_cleanup_state_check")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_lifecycle_status_check")
    for column in ("cleanup_completed_at", "cleanup_state", "deleted_by", "deleted_at", "lifecycle_status"):
        op.execute(f"ALTER TABLE documents DROP COLUMN IF EXISTS {column}")
