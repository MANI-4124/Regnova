"""create_evidence_table

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-09-07 00:00:06.000000

Collapses C8's Evidence + Evidence Link into one table for V1 - see
app/modules/evidence/models.py and CLAUDE.md "Document storage and
versioning" for the reasoning and the un-collapse trigger.
is_current/stale_reason mirror StateSnapshot's own currency fields,
set by DocumentVersionService.create() when the DocumentVersion an
Evidence row points at gets superseded.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = 'b6c7d8e9f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('evidence',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('document_version_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('requirement_version_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('stale_reason', sa.String(length=255), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_version_id'], ['document_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_version_id'], ['requirement_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_version_id', 'product_id', 'requirement_version_id', name='uq_evidence_link'),
    )
    op.create_index('ix_evidence_organization_id', 'evidence', ['organization_id'], unique=False)
    op.create_index('ix_evidence_document_version_id', 'evidence', ['document_version_id'], unique=False)
    op.create_index('ix_evidence_product_id', 'evidence', ['product_id'], unique=False)
    op.create_index('ix_evidence_requirement_version_id', 'evidence', ['requirement_version_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_evidence_requirement_version_id', table_name='evidence')
    op.drop_index('ix_evidence_product_id', table_name='evidence')
    op.drop_index('ix_evidence_document_version_id', table_name='evidence')
    op.drop_index('ix_evidence_organization_id', table_name='evidence')
    op.drop_table('evidence')
