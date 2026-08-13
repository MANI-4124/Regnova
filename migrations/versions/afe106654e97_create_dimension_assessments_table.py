"""create_dimension_assessments_table

Revision ID: afe106654e97
Revises: 4ab3ee310946
Create Date: 2026-08-12 15:03:18.375624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'afe106654e97'
down_revision: Union[str, Sequence[str], None] = '4ab3ee310946'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('dimension_assessments',
    sa.Column('assessment_run_id', sa.UUID(), nullable=False),
    sa.Column('dimension', sa.String(length=50), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assessment_run_id'], ['assessment_runs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dimension_assessments_assessment_run_id', 'dimension_assessments', ['assessment_run_id'], unique=False)
    op.create_index('ix_dimension_assessments_dimension', 'dimension_assessments', ['dimension'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_dimension_assessments_dimension', table_name='dimension_assessments')
    op.drop_index('ix_dimension_assessments_assessment_run_id', table_name='dimension_assessments')
    op.drop_table('dimension_assessments')
