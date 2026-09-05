"""add_source_human_reference_column

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sources', sa.Column('human_reference', sa.String(length=100), nullable=True))
    op.create_unique_constraint('uq_sources_human_reference', 'sources', ['human_reference'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_sources_human_reference', 'sources', type_='unique')
    op.drop_column('sources', 'human_reference')
