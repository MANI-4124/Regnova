"""create_state_snapshots_table

Revision ID: c7d4e91a2f6b
Revises: b6a1c9f3d8e2
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7d4e91a2f6b'
down_revision: Union[str, Sequence[str], None] = 'b6a1c9f3d8e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('state_snapshots',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('product_market_state_id', sa.UUID(), nullable=False),
    sa.Column('product_version_id', sa.UUID(), nullable=False),
    sa.Column('regulatory_basis_release_id', sa.UUID(), nullable=False),
    sa.Column('assessment_run_id', sa.UUID(), nullable=True),
    sa.Column('overall_gate', sa.String(length=10), nullable=False),
    sa.Column('raw_progress', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('displayed_progress', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('highest_open_severity', sa.String(length=30), nullable=True),
    sa.Column('readiness_reason_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outstanding_action_count', sa.Integer(), nullable=False),
    sa.Column('dimension_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('unresolved_severity_counts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('engine_build', sa.String(length=50), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('stale_reason', sa.String(length=255), nullable=True),
    sa.Column('superseded_by_snapshot_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_market_state_id'], ['product_market_states.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_version_id'], ['product_versions.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['regulatory_basis_release_id'], ['regulatory_basis_releases.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['assessment_run_id'], ['assessment_runs.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseded_by_snapshot_id'], ['state_snapshots.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_state_snapshots_organization_id', 'state_snapshots', ['organization_id'], unique=False)
    op.create_index('ix_state_snapshots_product_market_state_id', 'state_snapshots', ['product_market_state_id'], unique=False)
    op.create_index('ix_state_snapshots_is_current', 'state_snapshots', ['is_current'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_state_snapshots_is_current', table_name='state_snapshots')
    op.drop_index('ix_state_snapshots_product_market_state_id', table_name='state_snapshots')
    op.drop_index('ix_state_snapshots_organization_id', table_name='state_snapshots')
    op.drop_table('state_snapshots')
