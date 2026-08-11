"""create outbox_events table

Revision ID: e328fecfff3b
Revises: 686743c2e003
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e328fecfff3b'
down_revision: Union[str, Sequence[str], None] = '686743c2e003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('outbox_events',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('correlation_id', sa.String(length=100), nullable=True),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_outbox_events_dispatch', 'outbox_events', ['published_at', 'created_at'], unique=False)
    op.create_index('ix_outbox_events_organization_id', 'outbox_events', ['organization_id'], unique=False)
    op.create_index('ix_outbox_events_event_type', 'outbox_events', ['event_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_outbox_events_event_type', table_name='outbox_events')
    op.drop_index('ix_outbox_events_organization_id', table_name='outbox_events')
    op.drop_index('ix_outbox_events_dispatch', table_name='outbox_events')
    op.drop_table('outbox_events')
