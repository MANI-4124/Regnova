"""add_requirement_version_subject_kind_column

Revision ID: b6a1c9f3d8e2
Revises: 2d1c733684af
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6a1c9f3d8e2'
down_revision: Union[str, Sequence[str], None] = '2d1c733684af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('requirement_versions', sa.Column('subject_kind', sa.String(length=30), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('requirement_versions', 'subject_kind')
