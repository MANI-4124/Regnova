"""create product_versions table

Revision ID: 686743c2e003
Revises: 3cfccc35400d
Create Date: 2026-08-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '686743c2e003'
down_revision: Union[str, Sequence[str], None] = '3cfccc35400d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('product_versions',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id', 'version', name='uq_product_version_per_product')
    )
    op.create_index('ix_product_versions_organization_id', 'product_versions', ['organization_id'], unique=False)
    op.create_index('ix_product_versions_product_id', 'product_versions', ['product_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_product_versions_product_id', table_name='product_versions')
    op.drop_index('ix_product_versions_organization_id', table_name='product_versions')
    op.drop_table('product_versions')
