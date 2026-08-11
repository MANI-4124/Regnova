"""create requirements table

Revision ID: 58e09ef0df1a
Revises: bfee77e6558f
Create Date: 2026-08-11 00:00:03.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58e09ef0df1a'
down_revision: Union[str, Sequence[str], None] = 'bfee77e6558f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('requirements',
    sa.Column('human_reference', sa.String(length=100), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('human_reference')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('requirements')
