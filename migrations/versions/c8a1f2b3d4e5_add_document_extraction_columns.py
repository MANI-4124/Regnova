"""add_document_extraction_columns

Revision ID: c8a1f2b3d4e5
Revises: b7f3a1c9d2e5
Create Date: 2026-09-11 10:00:00.000000

Document extraction (FR-04's unbuilt half, first vertical slice - see
app/extraction/ and CLAUDE.md "Document extraction"). Additive, nullable,
no data migration, matching every prior AI-slice migration's shape:

  - document_versions.extraction_status    NULL = no extraction schema
                                           exists yet for this document's
                                           document_type (PROCESSING was
                                           never entered). "COMPLETED" or
                                           "FAILED" once a schema exists
                                           and PROCESSING ran. No separate
                                           "SKIPPED" value - null already
                                           means exactly that,
                                           unambiguously.
  - document_versions.extraction_error     set only when
                                           extraction_status == "FAILED".
  - document_field_revisions.ai_model_identifier   which model produced
                                           an AI_EXTRACTED revision.
  - document_field_revisions.ai_prompt_version     which extraction
                                           schema version produced it.

No new DocumentVersionStatus enum value needed here - PROCESSING is a
Python-side string like every other status in this codebase, not a DB
constraint.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8a1f2b3d4e5'
down_revision: Union[str, Sequence[str], None] = 'b7f3a1c9d2e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('document_versions', sa.Column('extraction_status', sa.String(length=20), nullable=True))
    op.add_column('document_versions', sa.Column('extraction_error', sa.Text(), nullable=True))
    op.add_column('document_field_revisions', sa.Column('ai_model_identifier', sa.String(length=100), nullable=True))
    op.add_column('document_field_revisions', sa.Column('ai_prompt_version', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('document_field_revisions', 'ai_prompt_version')
    op.drop_column('document_field_revisions', 'ai_model_identifier')
    op.drop_column('document_versions', 'extraction_error')
    op.drop_column('document_versions', 'extraction_status')
