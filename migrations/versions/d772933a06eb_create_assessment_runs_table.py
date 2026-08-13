"""create_assessment_runs_table

Revision ID: d772933a06eb
Revises: d29ce0526a3a
Create Date: 2026-08-12 15:03:17.080316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd772933a06eb'
down_revision: Union[str, Sequence[str], None] = 'd29ce0526a3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('assessment_runs',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('product_market_state_id', sa.UUID(), nullable=False),
    sa.Column('product_version_id', sa.UUID(), nullable=False),
    sa.Column('regulatory_basis_release_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('requested_by_user_id', sa.UUID(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_market_state_id'], ['product_market_states.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['regulatory_basis_release_id'], ['regulatory_basis_releases.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_assessment_runs_organization_id', 'assessment_runs', ['organization_id'], unique=False)
    op.create_index('ix_assessment_runs_product_market_state_id', 'assessment_runs', ['product_market_state_id'], unique=False)
    op.create_index('ix_assessment_runs_status', 'assessment_runs', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_assessment_runs_status', table_name='assessment_runs')
    op.drop_index('ix_assessment_runs_product_market_state_id', table_name='assessment_runs')
    op.drop_index('ix_assessment_runs_organization_id', table_name='assessment_runs')
    op.drop_table('assessment_runs')
