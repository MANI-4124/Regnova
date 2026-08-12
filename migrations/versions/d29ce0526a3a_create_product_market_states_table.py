"""create_product_market_states_table

Revision ID: d29ce0526a3a
Revises: c32f2479f062
Create Date: 2026-08-12 14:16:25.022391

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd29ce0526a3a'
down_revision: Union[str, Sequence[str], None] = 'c32f2479f062'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('product_market_states',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('product_version_id', sa.UUID(), nullable=True),
    sa.Column('market', sa.String(length=100), nullable=False),
    sa.Column('regulatory_basis_release_id', sa.UUID(), nullable=True),
    sa.Column('gate', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['regulatory_basis_release_id'], ['regulatory_basis_releases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pms_organization_id', 'product_market_states', ['organization_id'], unique=False)
    op.create_index('ix_pms_product_id', 'product_market_states', ['product_id'], unique=False)
    op.create_index('ix_pms_market', 'product_market_states', ['market'], unique=False)
    op.create_index(
        'uq_pms_active_per_product_market',
        'product_market_states',
        ['organization_id', 'product_id', 'market'],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_pms_active_per_product_market', table_name='product_market_states')
    op.drop_index('ix_pms_market', table_name='product_market_states')
    op.drop_index('ix_pms_product_id', table_name='product_market_states')
    op.drop_index('ix_pms_organization_id', table_name='product_market_states')
    op.drop_table('product_market_states')
