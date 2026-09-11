"""create_ask_regnova_queries_table

Revision ID: e4f5a6b7c8d9
Revises: d1e2f3a4b5c6
Create Date: 2026-09-12 09:30:00.000000

FR-11, Ask RegNova's query router - see app/modules/ask_regnova/ and
CLAUDE.md "Ask RegNova". One row per question asked, the same "universal
execution ledger" role StepRun plays for the assessment engine - not an
OutboxEvent/AuditEvent (those are for domain state changes; answering a
question changes nothing). organization_id is ondelete=CASCADE, like
Document/Evidence/Export - a query-history record, not a compliance
record of record the way AuditEvent (RESTRICT) is.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ask_regnova_queries',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('question_class', sa.String(length=30), nullable=False),
    sa.Column('intent', sa.String(length=50), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('model_identifier', sa.String(length=100), nullable=False),
    sa.Column('prompt_version', sa.String(length=50), nullable=False),
    sa.Column('structured_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('narrative', sa.Text(), nullable=False),
    sa.Column('degraded', sa.Boolean(), nullable=False),
    sa.Column('degraded_reason', sa.String(length=50), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ask_regnova_queries_organization_id', 'ask_regnova_queries', ['organization_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_ask_regnova_queries_organization_id', table_name='ask_regnova_queries')
    op.drop_table('ask_regnova_queries')
