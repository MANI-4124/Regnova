"""create rule_version_source_locations table

Revision ID: 361c3112393e
Revises: 626ac1ff4349
Create Date: 2026-08-12 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '361c3112393e'
down_revision: Union[str, Sequence[str], None] = '626ac1ff4349'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('rule_version_source_locations',
    sa.Column('rule_version_id', sa.UUID(), nullable=False),
    sa.Column('source_location_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['rule_version_id'], ['rule_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_location_id'], ['source_locations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('rule_version_id', 'source_location_id', name='uq_rule_version_source_location')
    )
    op.create_index('ix_rvsl2_rule_version_id', 'rule_version_source_locations', ['rule_version_id'], unique=False)
    op.create_index('ix_rvsl2_source_location_id', 'rule_version_source_locations', ['source_location_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rvsl2_source_location_id', table_name='rule_version_source_locations')
    op.drop_index('ix_rvsl2_rule_version_id', table_name='rule_version_source_locations')
    op.drop_table('rule_version_source_locations')
