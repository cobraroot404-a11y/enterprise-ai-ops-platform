"""Audit record of numeric measurements used (or rejected) when an incident was extracted.

Revision ID: 0007

Each element records the measurement name, unit, value, source, evidence span, verification status and, for an unsupported model-proposed
value, the original model value (never used by the priority rules). Existing rows get an empty list. Row-level security and grants of
`incidents` apply unchanged (table-level privileges cover the new column).
"""
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("ALTER TABLE incidents ADD COLUMN measurements jsonb NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported")
