"""create_document_versions_table

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-09-07 00:00:04.000000

Immutable binary + metadata snapshot (C8, FR-04). Status vocabulary is
deliberately narrowed to REVIEW_REQUIRED/VERIFIED/REJECTED/QUARANTINED -
see CLAUDE.md "Document storage and versioning" for why
Uploading/Scanning/Processing/Extracted/Failed are excluded.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('document_versions',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('checksum', sa.String(length=128), nullable=False),
    sa.Column('storage_backend', sa.String(length=20), nullable=False),
    sa.Column('original_filename', sa.String(length=500), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('uploaded_by_user_id', sa.UUID(), nullable=True),
    sa.Column('reviewed_by_user_id', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['document_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['document_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_document_versions_document_id', 'document_versions', ['document_id'], unique=False)
    op.create_index('ix_document_versions_organization_id', 'document_versions', ['organization_id'], unique=False)
    op.create_index('ix_document_versions_status', 'document_versions', ['status'], unique=False)
    op.create_index('ix_document_versions_checksum', 'document_versions', ['checksum'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_document_versions_checksum', table_name='document_versions')
    op.drop_index('ix_document_versions_status', table_name='document_versions')
    op.drop_index('ix_document_versions_organization_id', table_name='document_versions')
    op.drop_index('ix_document_versions_document_id', table_name='document_versions')
    op.drop_table('document_versions')
