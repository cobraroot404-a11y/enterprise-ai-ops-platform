"""Tenant-leading indexes for incidents, approvals and outbox_events (closes V41-17.03-IDX).

Revision ID: 0008

Why these three, and only these (from the real tenant-scoped queries):
  incidents       list endpoint and metrics: WHERE tenant_id = ? [filters] ORDER BY created_at DESC            -> (tenant_id, created_at DESC)
  approvals       decided-approvals list: WHERE tenant_id = ? ORDER BY decided_at DESC                         -> (tenant_id, decided_at DESC)
  outbox_events   workflow history and metrics: WHERE tenant_id = ? [status | aggregate_id] ORDER BY id DESC   -> (tenant_id, id DESC)
Lookups by id or ticket_id are already served by the primary keys and the unique index on approvals.ticket_id; the worker's cross-tenant claim query
(topic, status, available_at ordered by id) is not tenant-scoped and is deliberately not changed here.

Additive only: no data, constraint, foreign key, policy or grant is touched, so row-level security and privileges apply unchanged (indexes need no grants).

Locking: plain CREATE INDEX takes a SHARE lock that blocks writes to the table while the index builds. That is acceptable for the current local
development database (small tables, builds in milliseconds) and is NOT a zero-downtime claim for production: a large live deployment would create these
with CREATE INDEX CONCURRENTLY outside a transaction (Alembic autocommit_block) in a separate, reviewed step.
"""
from alembic import op

revision = "0008"
down_revision = "0007"

INDEXES = (
    ("incidents_tenant_created_idx", "incidents", "tenant_id, created_at DESC"),
    ("approvals_tenant_decided_idx", "approvals", "tenant_id, decided_at DESC"),
    ("outbox_events_tenant_id_idx", "outbox_events", "tenant_id, id DESC"),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} ({columns})")


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
