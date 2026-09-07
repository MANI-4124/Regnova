"""create_documents_table

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-07 00:00:03.000000

FR-04, storage and versioning only (no OCR/extraction) - see
CLAUDE.md "Document storage and versioning". document_type lives here,
not on document_versions - a deliberate deviation from the Source/
Requirement/Rule "everything descriptive lives on the Version"
convention, explained in app/modules/document/models.py and CLAUDE.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('documents',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('document_type', sa.String(length=50), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_documents_organization_id', 'documents', ['organization_id'], unique=False)
    op.create_index('ix_documents_document_type', 'documents', ['document_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_documents_document_type', table_name='documents')
    op.drop_index('ix_documents_organization_id', table_name='documents')
    op.drop_table('documents')
