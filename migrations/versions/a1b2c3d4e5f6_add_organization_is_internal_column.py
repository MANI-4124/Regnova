"""add_organization_is_internal_column

Revision ID: a1b2c3d4e5f6
Revises: c7d4e91a2f6b
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'c7d4e91a2f6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('organizations', sa.Column('is_internal', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(
        'uq_organizations_single_internal',
        'organizations',
        ['is_internal'],
        unique=True,
        postgresql_where=sa.text('is_internal = true'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_organizations_single_internal', table_name='organizations')
    op.drop_column('organizations', 'is_internal')
