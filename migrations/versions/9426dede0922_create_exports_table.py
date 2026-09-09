"""create_exports_table

Revision ID: 9426dede0922
Revises: d8e9f0a1b2c3
Create Date: 2026-09-09 00:00:00.000000

FR-14, second half - exports (findings CSV, evidence pack JSON). See
app/modules/export/service.py and CLAUDE.md "Exports". organization_id
is ondelete=CASCADE (unlike AuditEvent's own RESTRICT) - an export is a
generated artifact, not a compliance record of record; deleting the
organization it belongs to should take its exports with it, the same
as Document/Evidence/ProductMarketState.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9426dede0922'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('exports',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('export_type', sa.String(length=30), nullable=False),
    sa.Column('product_market_state_id', sa.UUID(), nullable=False),
    sa.Column('state_snapshot_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('checksum', sa.String(length=128), nullable=True),
    sa.Column('content_type', sa.String(length=100), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('requested_by_user_id', sa.UUID(), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_market_state_id'], ['product_market_states.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['state_snapshot_id'], ['state_snapshots.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_exports_organization_id', 'exports', ['organization_id'], unique=False)
    op.create_index('ix_exports_product_market_state_id', 'exports', ['product_market_state_id'], unique=False)
    op.create_index('ix_exports_state_snapshot_id', 'exports', ['state_snapshot_id'], unique=False)
    op.create_index('ix_exports_status', 'exports', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_exports_status', table_name='exports')
    op.drop_index('ix_exports_state_snapshot_id', table_name='exports')
    op.drop_index('ix_exports_product_market_state_id', table_name='exports')
    op.drop_index('ix_exports_organization_id', table_name='exports')
    op.drop_table('exports')
