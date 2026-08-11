"""create requirement_version_source_locations table

Revision ID: e3b5456208d7
Revises: a22f2a7e71d9
Create Date: 2026-08-11 00:00:05.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3b5456208d7'
down_revision: Union[str, Sequence[str], None] = 'a22f2a7e71d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('requirement_version_source_locations',
    sa.Column('requirement_version_id', sa.UUID(), nullable=False),
    sa.Column('source_location_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['requirement_version_id'], ['requirement_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_location_id'], ['source_locations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('requirement_version_id', 'source_location_id', name='uq_requirement_version_source_location')
    )
    op.create_index('ix_rvsl_requirement_version_id', 'requirement_version_source_locations', ['requirement_version_id'], unique=False)
    op.create_index('ix_rvsl_source_location_id', 'requirement_version_source_locations', ['source_location_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rvsl_source_location_id', table_name='requirement_version_source_locations')
    op.drop_index('ix_rvsl_requirement_version_id', table_name='requirement_version_source_locations')
    op.drop_table('requirement_version_source_locations')
