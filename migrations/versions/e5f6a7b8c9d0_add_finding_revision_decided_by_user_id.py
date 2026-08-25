"""add_finding_revision_decided_by_user_id

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'finding_revisions',
        sa.Column('decided_by_user_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_finding_revisions_decided_by_user_id',
        'finding_revisions', 'users',
        ['decided_by_user_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_finding_revisions_decided_by_user_id',
        'finding_revisions', type_='foreignkey',
    )
    op.drop_column('finding_revisions', 'decided_by_user_id')
