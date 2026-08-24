"""add_user_is_permanent_admin_column

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-23 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('is_permanent_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index(
        'uq_users_single_permanent_admin',
        'users',
        ['is_permanent_admin'],
        unique=True,
        postgresql_where=sa.text('is_permanent_admin = true'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_users_single_permanent_admin', table_name='users')
    op.drop_column('users', 'is_permanent_admin')
