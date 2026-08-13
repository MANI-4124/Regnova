"""create_step_runs_table

Revision ID: 4ab3ee310946
Revises: d772933a06eb
Create Date: 2026-08-12 15:03:17.712603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4ab3ee310946'
down_revision: Union[str, Sequence[str], None] = 'd772933a06eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('step_runs',
    sa.Column('assessment_run_id', sa.UUID(), nullable=False),
    sa.Column('dimension', sa.String(length=50), nullable=False),
    sa.Column('step_type', sa.String(length=30), nullable=False),
    sa.Column('rule_version_id', sa.UUID(), nullable=True),
    sa.Column('subject_key', sa.String(length=255), nullable=True),
    sa.Column('input_facts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=True),
    sa.Column('trace', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assessment_run_id'], ['assessment_runs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_version_id'], ['rule_versions.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_step_runs_assessment_run_id', 'step_runs', ['assessment_run_id'], unique=False)
    op.create_index('ix_step_runs_dimension', 'step_runs', ['dimension'], unique=False)
    op.create_index('ix_step_runs_rule_version_id', 'step_runs', ['rule_version_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_step_runs_rule_version_id', table_name='step_runs')
    op.drop_index('ix_step_runs_dimension', table_name='step_runs')
    op.drop_index('ix_step_runs_assessment_run_id', table_name='step_runs')
    op.drop_table('step_runs')
