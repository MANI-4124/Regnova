"""create_internal_role_assignments_table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-23 00:00:00.000002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('internal_role_assignments',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role_code', sa.String(length=50), nullable=False),
    sa.Column('scope', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('proposed_by_user_id', sa.UUID(), nullable=True),
    sa.Column('proposed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('approver_user_id', sa.UUID(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_rationale', sa.Text(), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('revocation_proposed_by_user_id', sa.UUID(), nullable=True),
    sa.Column('revocation_proposed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revocation_rationale', sa.Text(), nullable=True),
    sa.Column('revoked_by_user_id', sa.UUID(), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revocation_reason', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('superseded_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proposed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['approver_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['revocation_proposed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['revoked_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['superseded_by_id'], ['internal_role_assignments.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_internal_role_assignments_user_id', 'internal_role_assignments', ['user_id'], unique=False)
    op.create_index('ix_internal_role_assignments_role_code', 'internal_role_assignments', ['role_code'], unique=False)
    op.create_index('ix_internal_role_assignments_status', 'internal_role_assignments', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_internal_role_assignments_status', table_name='internal_role_assignments')
    op.drop_index('ix_internal_role_assignments_role_code', table_name='internal_role_assignments')
    op.drop_index('ix_internal_role_assignments_user_id', table_name='internal_role_assignments')
    op.drop_table('internal_role_assignments')
