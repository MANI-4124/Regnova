"""create regulatory_basis_releases table

Revision ID: 8b9f325565de
Revises: 361c3112393e
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8b9f325565de'
down_revision: Union[str, Sequence[str], None] = '361c3112393e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('regulatory_basis_releases',
    sa.Column('jurisdiction', sa.String(length=100), nullable=False),
    sa.Column('market', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('content_hash', sa.String(length=128), nullable=False),
    sa.Column('configuration', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('configuration_schema_name', sa.String(length=100), nullable=True),
    sa.Column('configuration_schema_version', sa.Integer(), nullable=True),
    sa.Column('author_user_id', sa.UUID(), nullable=True),
    sa.Column('reviewer_user_id', sa.UUID(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['supersedes_id'], ['regulatory_basis_releases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['regulatory_basis_releases.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_hash')
    )
    op.create_index('ix_rbr_jurisdiction', 'regulatory_basis_releases', ['jurisdiction'], unique=False)
    op.create_index('ix_rbr_market', 'regulatory_basis_releases', ['market'], unique=False)
    op.create_index('ix_rbr_status', 'regulatory_basis_releases', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rbr_status', table_name='regulatory_basis_releases')
    op.drop_index('ix_rbr_market', table_name='regulatory_basis_releases')
    op.drop_index('ix_rbr_jurisdiction', table_name='regulatory_basis_releases')
    op.drop_table('regulatory_basis_releases')
