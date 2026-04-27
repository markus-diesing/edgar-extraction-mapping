"""add_par_value

Adds ``par_value`` to ``underlying_securities`` to store the par value
extracted from the 10-K cover page separately from the share class name.

Previously ``share_class_name`` stored the combined string
(e.g. "Common Stock, $0.001 par value").  The LLM now returns the class
name alone (e.g. "Class A Common Stock") in ``share_class_name`` and the
par value string (e.g. "$0.001 par value") in the new ``par_value`` column.

- ``par_value`` TEXT  — e.g. "$0.001 par value", "no par value", or NULL

Revision ID: d7e8f9a0b1c2
Revises: a8f2c6e91d34
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect as _sa_inspect
from alembic import op

revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'a8f2c6e91d34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {c['name'] for c in _sa_inspect(bind).get_columns('underlying_securities')}
    if 'par_value' not in existing:
        with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
            batch_op.add_column(sa.Column('par_value', sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    existing = {c['name'] for c in _sa_inspect(bind).get_columns('underlying_securities')}
    if 'par_value' in existing:
        with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
            batch_op.drop_column('par_value')
