"""create_document_field_tables

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-09-07 00:00:05.000000

Manual structured-field entry (FR-04's stand-in for OCR/extraction) -
document_fields is the stable per-field identity, document_field_revisions
the append-only value/confidence history (AC-FR-04-02: corrections
create a revision, never an overwrite). confidence has no default at
the DB level - application code leaves it null unless a caller supplies
one; see CLAUDE.md "Document storage and versioning".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, Sequence[str], None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('document_fields',
    sa.Column('document_version_id', sa.UUID(), nullable=False),
    sa.Column('field_key', sa.String(length=100), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_version_id', 'field_key', name='uq_document_field_key'),
    )
    op.create_index('ix_document_fields_document_version_id', 'document_fields', ['document_version_id'], unique=False)

    op.create_table('document_field_revisions',
    sa.Column('document_field_id', sa.UUID(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('location', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('entered_by_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_field_id'], ['document_fields.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['entered_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_field_id', 'revision_number', name='uq_document_field_revision_number'),
    )
    op.create_index('ix_document_field_revisions_document_field_id', 'document_field_revisions', ['document_field_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_document_field_revisions_document_field_id', table_name='document_field_revisions')
    op.drop_table('document_field_revisions')
    op.drop_index('ix_document_fields_document_version_id', table_name='document_fields')
    op.drop_table('document_fields')
