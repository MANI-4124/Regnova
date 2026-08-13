"""create_requirement_results_table

Revision ID: 80a0eac71dfc
Revises: afe106654e97
Create Date: 2026-08-12 15:03:19.007376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '80a0eac71dfc'
down_revision: Union[str, Sequence[str], None] = 'afe106654e97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('requirement_results',
    sa.Column('step_run_id', sa.UUID(), nullable=False),
    sa.Column('assessment_run_id', sa.UUID(), nullable=False),
    sa.Column('requirement_version_id', sa.UUID(), nullable=False),
    sa.Column('rule_version_id', sa.UUID(), nullable=True),
    sa.Column('outcome', sa.String(length=30), nullable=False),
    sa.Column('predicate_inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['step_run_id'], ['step_runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['assessment_run_id'], ['assessment_runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_version_id'], ['requirement_versions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_version_id'], ['rule_versions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('step_run_id', name='uq_requirement_result_step_run'),
    )
    op.create_index('ix_requirement_results_assessment_run_id', 'requirement_results', ['assessment_run_id'], unique=False)
    op.create_index('ix_requirement_results_requirement_version_id', 'requirement_results', ['requirement_version_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_requirement_results_requirement_version_id', table_name='requirement_results')
    op.drop_index('ix_requirement_results_assessment_run_id', table_name='requirement_results')
    op.drop_table('requirement_results')
