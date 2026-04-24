"""add_legal_name_and_llm_tokens

Adds the following columns to ``underlying_securities``:

- ``legal_name``       TEXT    — registrant's legal name extracted from the 10-K cover
                                 page by the Tier 2 LLM pipeline (distinct from the
                                 all-caps ``company_name`` sourced from the submissions API)
- ``llm_input_tokens`` INTEGER — prompt tokens consumed by the Tier 2 extraction call
- ``llm_output_tokens`` INTEGER — completion tokens consumed
- ``llm_cost_usd``     REAL    — estimated USD cost at list-price rates

Revision ID: b9f4a1c72e83
Revises: e421f7a39fcf
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect as _sa_inspect
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9f4a1c72e83'
down_revision: Union[str, Sequence[str], None] = 'e421f7a39fcf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard against databases where _migrate() already added these columns before
    # this Alembic revision was stamped (e.g. after a manual `alembic stamp`).
    bind = op.get_bind()
    existing = {c['name'] for c in _sa_inspect(bind).get_columns('underlying_securities')}
    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        if 'legal_name' not in existing:
            batch_op.add_column(sa.Column('legal_name',         sa.String(),  nullable=True))
        if 'llm_input_tokens' not in existing:
            batch_op.add_column(sa.Column('llm_input_tokens',  sa.Integer(), nullable=True))
        if 'llm_output_tokens' not in existing:
            batch_op.add_column(sa.Column('llm_output_tokens', sa.Integer(), nullable=True))
        if 'llm_cost_usd' not in existing:
            batch_op.add_column(sa.Column('llm_cost_usd',      sa.Float(),   nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('underlying_securities', schema=None) as batch_op:
        batch_op.drop_column('llm_cost_usd')
        batch_op.drop_column('llm_output_tokens')
        batch_op.drop_column('llm_input_tokens')
        batch_op.drop_column('legal_name')
