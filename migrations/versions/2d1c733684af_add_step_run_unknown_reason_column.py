"""add_step_run_unknown_reason_column

Revision ID: 2d1c733684af
Revises: 54aa9cfd3357
Create Date: 2026-08-13 12:18:51.286639

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d1c733684af'
down_revision: Union[str, Sequence[str], None] = '54aa9cfd3357'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('step_runs', sa.Column('unknown_reason', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('step_runs', 'unknown_reason')
