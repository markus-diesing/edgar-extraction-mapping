"""add_h3_underlying_indexes

H3 schema hardening (review cycle 2026-04-24):

- underlying_securities: add named UniqueConstraint(cik, ticker) so the
  constraint is visible in schema introspection tools (was a SQLite autoindex).
- underlying_securities: add explicit composite Index(cik, ticker) for the
  upsert hot-path in background.py.
- underlying_securities: add Index(status) and Index(ingest_timestamp) for
  the list endpoint's common filter and sort patterns.
- underlying_field_results: add named UniqueConstraint(underlying_id, field_name)
  for the same introspection reason.

Revision ID: a1b2c3d4e5f6
Revises: 6218180d8918
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '6218180d8918'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add H3 indexes and named constraints to underlying tables."""

    # ── underlying_securities ──────────────────────────────────────────────
    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        # Named unique constraint on (cik, ticker) — replaces the unnamed
        # sqlite_autoindex that create_all() generated.
        batch_op.create_unique_constraint(
            'uq_underlying_cik_ticker', ['cik', 'ticker']
        )
        # Explicit composite index for upsert lookups (background.py filter_by).
        batch_op.create_index(
            'ix_underlying_cik_ticker', ['cik', 'ticker'], unique=False
        )
        # Single-column indexes for common list-endpoint filters.
        batch_op.create_index(
            'ix_underlying_securities_status', ['status'], unique=False
        )
        batch_op.create_index(
            'ix_underlying_securities_ingest_timestamp', ['ingest_timestamp'], unique=False
        )

    # ── underlying_field_results ───────────────────────────────────────────
    with op.batch_alter_table('underlying_field_results', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_field_result_underlying_field', ['underlying_id', 'field_name']
        )


def downgrade() -> None:
    """Remove H3 indexes and named constraints."""

    with op.batch_alter_table('underlying_field_results', schema=None) as batch_op:
        batch_op.drop_constraint('uq_field_result_underlying_field', type_='unique')

    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        batch_op.drop_index('ix_underlying_securities_ingest_timestamp')
        batch_op.drop_index('ix_underlying_securities_status')
        batch_op.drop_index('ix_underlying_cik_ticker')
        batch_op.drop_constraint('uq_underlying_cik_ticker', type_='unique')
