"""create source_versions table

Revision ID: 25499ee27401
Revises: 7a1c27b55c5f
Create Date: 2026-08-11 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25499ee27401'
down_revision: Union[str, Sequence[str], None] = '7a1c27b55c5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('source_versions',
    sa.Column('source_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('issuing_authority', sa.String(length=255), nullable=False),
    sa.Column('jurisdiction', sa.String(length=100), nullable=False),
    sa.Column('tier', sa.Integer(), nullable=False),
    sa.Column('source_type', sa.String(length=100), nullable=False),
    sa.Column('official_url', sa.String(length=1000), nullable=True),
    sa.Column('file_checksum', sa.String(length=128), nullable=True),
    sa.Column('canonical_text_checksum', sa.String(length=128), nullable=True),
    sa.Column('language', sa.String(length=20), nullable=True),
    sa.Column('translation_status', sa.String(length=30), nullable=False),
    sa.Column('retrieval_method', sa.String(length=100), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('author_user_id', sa.UUID(), nullable=True),
    sa.Column('reviewer_user_id', sa.UUID(), nullable=True),
    sa.Column('license_notes', sa.Text(), nullable=True),
    sa.Column('usage_restrictions', sa.Text(), nullable=True),
    sa.Column('is_full_text_displayable', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['source_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['source_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_source_versions_source_id', 'source_versions', ['source_id'], unique=False)
    op.create_index('ix_source_versions_status', 'source_versions', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_source_versions_status', table_name='source_versions')
    op.drop_index('ix_source_versions_source_id', table_name='source_versions')
    op.drop_table('source_versions')
