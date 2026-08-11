"""create source_locations table

Revision ID: bfee77e6558f
Revises: 25499ee27401
Create Date: 2026-08-11 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfee77e6558f'
down_revision: Union[str, Sequence[str], None] = '25499ee27401'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('source_locations',
    sa.Column('source_version_id', sa.UUID(), nullable=False),
    sa.Column('section', sa.String(length=100), nullable=True),
    sa.Column('article', sa.String(length=100), nullable=True),
    sa.Column('schedule', sa.String(length=100), nullable=True),
    sa.Column('page', sa.String(length=50), nullable=True),
    sa.Column('table_ref', sa.String(length=50), nullable=True),
    sa.Column('paragraph', sa.String(length=100), nullable=True),
    sa.Column('normalized_text', sa.Text(), nullable=True),
    sa.Column('ocr_confidence', sa.Numeric(precision=4, scale=3), nullable=True),
    sa.Column('is_manually_corrected', sa.Boolean(), nullable=False),
    sa.Column('original_ocr_text', sa.Text(), nullable=True),
    sa.Column('corrected_by_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['source_version_id'], ['source_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['corrected_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_source_locations_source_version_id', 'source_locations', ['source_version_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_source_locations_source_version_id', table_name='source_locations')
    op.drop_table('source_locations')
