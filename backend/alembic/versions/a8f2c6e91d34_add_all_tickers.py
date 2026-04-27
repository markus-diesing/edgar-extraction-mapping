"""add_all_tickers

Adds ``all_tickers`` to ``underlying_securities`` to store the full list of
ticker symbols associated with a CIK's EDGAR submissions record.

For companies with a single listing this is a one-element list (e.g. ["MSFT"]).
For multi-class companies (e.g. KKR with KKR, KKR-PD, KKRS, KKRT) it contains
all listed series, enabling the UI to display sibling tickers even though the
row itself represents only one resolved share class.

- ``all_tickers`` TEXT  — JSON-encoded list, e.g. '["KKR","KKR-PD","KKRS","KKRT"]'

Revision ID: a8f2c6e91d34
Revises: c3e7d2f85a19
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect as _sa_inspect
from alembic import op

revision: str = 'a8f2c6e91d34'
down_revision: Union[str, Sequence[str], None] = 'c3e7d2f85a19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard against databases where _migrate() already added this column before
    # this Alembic revision was stamped (e.g. after a manual `alembic stamp`).
    bind = op.get_bind()
    existing = {c['name'] for c in _sa_inspect(bind).get_columns('underlying_securities')}
    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        if 'all_tickers' not in existing:
            batch_op.add_column(sa.Column('all_tickers', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        batch_op.drop_column('all_tickers')
