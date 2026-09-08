"""create_audit_events_table

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-09-08 00:00:00.000000

FR-14, first pass - the durable, tiered audit log consumed from the
outbox (see app/modules/audit/service.py and CLAUDE.md "Audit log").
organization_id is ondelete=RESTRICT, deliberately not CASCADE like
OutboxEvent - a customer's compliance record must outlive their
account (C15); deleting an Organization with audit history is refused
outright (also enforced at the service layer, since SQLite in this
project's test suite does not enforce foreign keys at all).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_events',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('source_event_id', sa.UUID(), nullable=True),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('correlation_id', sa.String(length=100), nullable=True),
    sa.Column('product_id', sa.UUID(), nullable=True),
    sa.Column('product_market_state_id', sa.UUID(), nullable=True),
    sa.Column('visibility_tier', sa.String(length=30), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('internal_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('retention_class', sa.String(length=30), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_event_id'], ['outbox_events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_market_state_id'], ['product_market_states.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_event_id'),
    )
    op.create_index('ix_audit_events_organization_id', 'audit_events', ['organization_id'], unique=False)
    op.create_index('ix_audit_events_product_id', 'audit_events', ['product_id'], unique=False)
    op.create_index('ix_audit_events_product_market_state_id', 'audit_events', ['product_market_state_id'], unique=False)
    op.create_index('ix_audit_events_actor_user_id', 'audit_events', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_events_event_type', 'audit_events', ['event_type'], unique=False)
    op.create_index('ix_audit_events_visibility_tier', 'audit_events', ['visibility_tier'], unique=False)
    op.create_index('ix_audit_events_occurred_at', 'audit_events', ['occurred_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_audit_events_occurred_at', table_name='audit_events')
    op.drop_index('ix_audit_events_visibility_tier', table_name='audit_events')
    op.drop_index('ix_audit_events_event_type', table_name='audit_events')
    op.drop_index('ix_audit_events_actor_user_id', table_name='audit_events')
    op.drop_index('ix_audit_events_product_market_state_id', table_name='audit_events')
    op.drop_index('ix_audit_events_product_id', table_name='audit_events')
    op.drop_index('ix_audit_events_organization_id', table_name='audit_events')
    op.drop_table('audit_events')
