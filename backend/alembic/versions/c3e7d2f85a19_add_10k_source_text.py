"""add_10k_source_text

Adds two columns to ``underlying_securities`` to enable human validation of
LLM-extracted fields against the actual 10-K filing text:

- ``last_10k_text``        TEXT    — first UNDERLYING_EXTRACTION_CHARS characters
                                     of the stripped 10-K text (the exact input
                                     slice used for LLM extraction)
- ``last_10k_primary_doc`` TEXT    — primary document filename from the EDGAR
                                     submissions API (e.g. "msft-20250630.htm"),
                                     used to construct a direct link to the filing

Revision ID: c3e7d2f85a19
Revises: b9f4a1c72e83
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3e7d2f85a19'
down_revision: Union[str, Sequence[str], None] = 'b9f4a1c72e83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_10k_text',        sa.Text(),   nullable=True))
        batch_op.add_column(sa.Column('last_10k_primary_doc', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        batch_op.drop_column('last_10k_primary_doc')
        batch_op.drop_column('last_10k_text')
