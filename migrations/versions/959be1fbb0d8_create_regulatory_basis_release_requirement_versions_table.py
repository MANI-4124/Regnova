"""create regulatory_basis_release_requirement_versions table

Revision ID: 959be1fbb0d8
Revises: e0a583399a57
Create Date: 2026-08-12 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '959be1fbb0d8'
down_revision: Union[str, Sequence[str], None] = 'e0a583399a57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('regulatory_basis_release_requirement_versions',
    sa.Column('release_id', sa.UUID(), nullable=False),
    sa.Column('requirement_version_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['release_id'], ['regulatory_basis_releases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_version_id'], ['requirement_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_id', 'requirement_version_id', name='uq_rbr_requirement_version')
    )
    op.create_index('ix_rbrrv_release_id', 'regulatory_basis_release_requirement_versions', ['release_id'], unique=False)
    op.create_index('ix_rbrrv_requirement_version_id', 'regulatory_basis_release_requirement_versions', ['requirement_version_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rbrrv_requirement_version_id', table_name='regulatory_basis_release_requirement_versions')
    op.drop_index('ix_rbrrv_release_id', table_name='regulatory_basis_release_requirement_versions')
    op.drop_table('regulatory_basis_release_requirement_versions')
