"""add_claims_semantic_analysis_columns

Revision ID: b7f3a1c9d2e5
Revises: 81cd457ccbfd
Create Date: 2026-09-10 12:00:00.000000

Claims semantic analysis (narrow AI slice) - see app/analysis/ and CLAUDE.md
"Claims semantic analysis". Additive, nullable, no data migration, no enum
constraints (all plain strings Python-side, matching every status/vocabulary
column in this codebase):

  - rule_versions.ai_analysis_mode        NULL = deterministic only (default,
                                          every existing rule). "SEMANTIC_EQUIVALENCE"
                                          opts a CLAIMS FINDING_PROPOSAL rule into
                                          the AI peer hop.
  - finding_revisions.analysis_method     NULL = deterministic/human-written
                                          revision. "AI_SEMANTIC" = raised by the hop.
  - finding_revisions.ai_model_identifier  which model produced an AI proposal.
  - finding_revisions.ai_prompt_version    which prompt version produced it.

No StepRun column: the AI hop's StepRun uses the already-existing
StepType.AI_ANALYSIS value.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f3a1c9d2e5'
down_revision: Union[str, Sequence[str], None] = '81cd457ccbfd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('rule_versions', sa.Column('ai_analysis_mode', sa.String(length=50), nullable=True))
    op.add_column('finding_revisions', sa.Column('analysis_method', sa.String(length=30), nullable=True))
    op.add_column('finding_revisions', sa.Column('ai_model_identifier', sa.String(length=100), nullable=True))
    op.add_column('finding_revisions', sa.Column('ai_prompt_version', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('finding_revisions', 'ai_prompt_version')
    op.drop_column('finding_revisions', 'ai_model_identifier')
    op.drop_column('finding_revisions', 'analysis_method')
    op.drop_column('rule_versions', 'ai_analysis_mode')
