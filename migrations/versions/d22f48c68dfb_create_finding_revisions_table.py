"""create_finding_revisions_table

Revision ID: d22f48c68dfb
Revises: 289fe953198d
Create Date: 2026-08-12 15:03:20.970377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd22f48c68dfb'
down_revision: Union[str, Sequence[str], None] = '289fe953198d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('finding_revisions',
    sa.Column('finding_id', sa.UUID(), nullable=False),
    sa.Column('revision_number', sa.Integer(), nullable=False),
    sa.Column('assessment_run_id', sa.UUID(), nullable=True),
    sa.Column('issue_type', sa.String(length=100), nullable=False),
    sa.Column('observed_value', sa.Text(), nullable=False),
    sa.Column('normalized_value', sa.Text(), nullable=True),
    sa.Column('observed_location', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('severity', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('disposition', sa.String(length=50), nullable=True),
    sa.Column('hard_gate_effect', sa.Boolean(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('action_type', sa.String(length=50), nullable=True),
    sa.Column('suggested_value', sa.Text(), nullable=True),
    sa.Column('resolution_criteria', sa.Text(), nullable=True),
    sa.Column('owner_user_id', sa.UUID(), nullable=True),
    sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution_decision', sa.String(length=50), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('superseding_finding_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['assessment_run_id'], ['assessment_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseding_finding_id'], ['findings.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('finding_id', 'revision_number', name='uq_finding_revision_number'),
    )
    op.create_index('ix_finding_revisions_finding_id', 'finding_revisions', ['finding_id'], unique=False)
    op.create_index('ix_finding_revisions_assessment_run_id', 'finding_revisions', ['assessment_run_id'], unique=False)
    op.create_index('ix_finding_revisions_status', 'finding_revisions', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_finding_revisions_status', table_name='finding_revisions')
    op.drop_index('ix_finding_revisions_assessment_run_id', table_name='finding_revisions')
    op.drop_index('ix_finding_revisions_finding_id', table_name='finding_revisions')
    op.drop_table('finding_revisions')
