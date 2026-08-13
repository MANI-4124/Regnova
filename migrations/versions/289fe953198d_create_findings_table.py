"""create_findings_table

Revision ID: 289fe953198d
Revises: 2c87259784a2
Create Date: 2026-08-12 15:03:20.323116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '289fe953198d'
down_revision: Union[str, Sequence[str], None] = '2c87259784a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('findings',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('product_market_state_id', sa.UUID(), nullable=False),
    sa.Column('dimension', sa.String(length=50), nullable=False),
    sa.Column('requirement_version_id', sa.UUID(), nullable=True),
    sa.Column('rule_version_id', sa.UUID(), nullable=True),
    sa.Column('subject_key', sa.String(length=255), nullable=True),
    sa.Column('human_reference', sa.String(length=100), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_market_state_id'], ['product_market_states.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_version_id'], ['requirement_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['rule_version_id'], ['rule_versions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_findings_organization_id', 'findings', ['organization_id'], unique=False)
    op.create_index('ix_findings_product_market_state_id', 'findings', ['product_market_state_id'], unique=False)
    op.create_index('ix_findings_dimension', 'findings', ['dimension'], unique=False)
    op.create_index(
        'ix_findings_identity_lookup',
        'findings',
        ['product_market_state_id', 'requirement_version_id', 'subject_key'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_findings_identity_lookup', table_name='findings')
    op.drop_index('ix_findings_dimension', table_name='findings')
    op.drop_index('ix_findings_product_market_state_id', table_name='findings')
    op.drop_index('ix_findings_organization_id', table_name='findings')
    op.drop_table('findings')
