"""create requirement_versions table

Revision ID: a22f2a7e71d9
Revises: 58e09ef0df1a
Create Date: 2026-08-11 00:00:04.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a22f2a7e71d9'
down_revision: Union[str, Sequence[str], None] = '58e09ef0df1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('requirement_versions',
    sa.Column('requirement_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('jurisdiction', sa.String(length=100), nullable=False),
    sa.Column('market', sa.String(length=100), nullable=False),
    sa.Column('authority', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=100), nullable=False),
    sa.Column('subcategory', sa.String(length=100), nullable=True),
    sa.Column('pathway', sa.String(length=100), nullable=True),
    sa.Column('dimension', sa.String(length=50), nullable=False),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('context_schema_name', sa.String(length=100), nullable=True),
    sa.Column('context_schema_version', sa.Integer(), nullable=True),
    sa.Column('applicability_predicate', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('applicability_predicate_schema_name', sa.String(length=100), nullable=True),
    sa.Column('applicability_predicate_schema_version', sa.Integer(), nullable=True),
    sa.Column('applicability_required_inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('unknown_behavior', sa.String(length=30), nullable=False),
    sa.Column('obligation_type', sa.String(length=100), nullable=False),
    sa.Column('canonical_statement', sa.Text(), nullable=False),
    sa.Column('customer_safe_explanation', sa.Text(), nullable=True),
    sa.Column('accepted_evidence_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('field_checks', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('validity_scope_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('verification_level', sa.String(length=100), nullable=True),
    sa.Column('default_severity', sa.String(length=30), nullable=False),
    sa.Column('is_hard_gate', sa.Boolean(), nullable=False),
    sa.Column('importance_weight', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('approval_policy', sa.String(length=100), nullable=True),
    sa.Column('author_user_id', sa.UUID(), nullable=True),
    sa.Column('reviewer_user_id', sa.UUID(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('authority_interpretation_label', sa.String(length=30), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('supersedes_id', sa.UUID(), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['requirement_id'], ['requirements.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supersedes_id'], ['requirement_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['requirement_versions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_requirement_versions_requirement_id', 'requirement_versions', ['requirement_id'], unique=False)
    op.create_index('ix_requirement_versions_status', 'requirement_versions', ['status'], unique=False)
    op.create_index('ix_requirement_versions_dimension', 'requirement_versions', ['dimension'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_requirement_versions_dimension', table_name='requirement_versions')
    op.drop_index('ix_requirement_versions_status', table_name='requirement_versions')
    op.drop_index('ix_requirement_versions_requirement_id', table_name='requirement_versions')
    op.drop_table('requirement_versions')
