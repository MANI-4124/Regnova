"""create_requirement_result_source_locations_table

Revision ID: 2c87259784a2
Revises: 80a0eac71dfc
Create Date: 2026-08-12 15:03:19.674866

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c87259784a2'
down_revision: Union[str, Sequence[str], None] = '80a0eac71dfc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('requirement_result_source_locations',
    sa.Column('requirement_result_id', sa.UUID(), nullable=False),
    sa.Column('source_location_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['requirement_result_id'], ['requirement_results.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_location_id'], ['source_locations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('requirement_result_id', 'source_location_id', name='uq_requirement_result_source_location'),
    )
    op.create_index('ix_rrsl_requirement_result_id', 'requirement_result_source_locations', ['requirement_result_id'], unique=False)
    op.create_index('ix_rrsl_source_location_id', 'requirement_result_source_locations', ['source_location_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rrsl_source_location_id', table_name='requirement_result_source_locations')
    op.drop_index('ix_rrsl_requirement_result_id', table_name='requirement_result_source_locations')
    op.drop_table('requirement_result_source_locations')
