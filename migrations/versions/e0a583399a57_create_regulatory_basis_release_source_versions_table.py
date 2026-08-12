"""create regulatory_basis_release_source_versions table

Revision ID: e0a583399a57
Revises: 8b9f325565de
Create Date: 2026-08-12 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0a583399a57'
down_revision: Union[str, Sequence[str], None] = '8b9f325565de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('regulatory_basis_release_source_versions',
    sa.Column('release_id', sa.UUID(), nullable=False),
    sa.Column('source_version_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['release_id'], ['regulatory_basis_releases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_version_id'], ['source_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_id', 'source_version_id', name='uq_rbr_source_version')
    )
    op.create_index('ix_rbrsv_release_id', 'regulatory_basis_release_source_versions', ['release_id'], unique=False)
    op.create_index('ix_rbrsv_source_version_id', 'regulatory_basis_release_source_versions', ['source_version_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rbrsv_source_version_id', table_name='regulatory_basis_release_source_versions')
    op.drop_index('ix_rbrsv_release_id', table_name='regulatory_basis_release_source_versions')
    op.drop_table('regulatory_basis_release_source_versions')
