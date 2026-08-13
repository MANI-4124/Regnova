"""create_finding_revision_source_locations_table

Revision ID: 54aa9cfd3357
Revises: d22f48c68dfb
Create Date: 2026-08-12 15:03:21.609780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54aa9cfd3357'
down_revision: Union[str, Sequence[str], None] = 'd22f48c68dfb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('finding_revision_source_locations',
    sa.Column('finding_revision_id', sa.UUID(), nullable=False),
    sa.Column('source_location_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['finding_revision_id'], ['finding_revisions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_location_id'], ['source_locations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('finding_revision_id', 'source_location_id', name='uq_finding_revision_source_location'),
    )
    op.create_index('ix_frsl_finding_revision_id', 'finding_revision_source_locations', ['finding_revision_id'], unique=False)
    op.create_index('ix_frsl_source_location_id', 'finding_revision_source_locations', ['source_location_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_frsl_source_location_id', table_name='finding_revision_source_locations')
    op.drop_index('ix_frsl_finding_revision_id', table_name='finding_revision_source_locations')
    op.drop_table('finding_revision_source_locations')
