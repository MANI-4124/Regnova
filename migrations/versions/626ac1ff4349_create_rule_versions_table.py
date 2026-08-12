"""create rule_versions table

Revision ID: 626ac1ff4349
Revises: 99af92f1fbf1
Create Date: 2026-08-12 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '626ac1ff4349'
down_revision: Union[str, Sequence[str], None] = '99af92f1fbf1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('rule_versions',
    sa.Column('rule_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('requirement_version_id', sa.UUID(), nullable=True),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('inputs_schema_name', sa.String(length=100), nullable=True),
    sa.Column('inputs_schema_version', sa.Integer(), nullable=True),
    sa.Column('condition', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('condition_schema_name', sa.String(length=100), nullable=True),
    sa.Column('condition_schema_version', sa.Integer(), nullable=True),
    sa.Column('unknown_behavior', sa.String(length=30), nullable=False),
    sa.Column('output_type', sa.String(length=30), nullable=False),
    sa.Column('author_user_id', sa.UUID(), nullable=True),
    sa.Column('reviewer_user_id', sa.UUID(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approval_policy', sa.String(length=100), nullable=True),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('test_fixtures', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('test_fixtures_schema_name', sa.String(length=100), nullable=True),
    sa.Column('test_fixtures_schema_version', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['rule_id'], ['rules.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requirement_version_id'], ['requirement_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['rule_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['rule_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_rule_versions_rule_id', 'rule_versions', ['rule_id'], unique=False)
    op.create_index('ix_rule_versions_status', 'rule_versions', ['status'], unique=False)
    op.create_index('ix_rule_versions_requirement_version_id', 'rule_versions', ['requirement_version_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rule_versions_requirement_version_id', table_name='rule_versions')
    op.drop_index('ix_rule_versions_status', table_name='rule_versions')
    op.drop_index('ix_rule_versions_rule_id', table_name='rule_versions')
    op.drop_table('rule_versions')
