"""add_dimension_assessment_submitted_facts_hash

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'dimension_assessments',
        sa.Column('submitted_facts_hash', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('dimension_assessments', 'submitted_facts_hash')
