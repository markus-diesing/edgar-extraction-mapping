"""baseline_existing_schema

This migration marks the state of the database as it existed before Alembic was
introduced.  All tables were created by SQLAlchemy's ``create_all()`` combined
with the hand-rolled ``_migrate()`` function in database.py.

No DDL is emitted — this revision is purely a historical marker.
Stamp the live DB to this revision with:

    alembic stamp 6218180d8918

then run the next migration to apply the H3 schema additions.

Revision ID: 6218180d8918
Revises:
Create Date: 2026-04-24
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '6218180d8918'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: baseline marker only."""


def downgrade() -> None:
    """No-op: baseline marker only."""
