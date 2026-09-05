"""create_content_version_transitions_table

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-09-05 00:00:00.000000

"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Backfilled (id, to_status='ACTIVE') rows recording that this version
# reached ACTIVE before the verify()/activate() workflow existed - see
# the data migration at the bottom of upgrade(). Not silently
# grandfathered: CLAUDE.md "Regulatory content approval workflow"
# records the decision that pre-existing ACTIVE content's provenance
# must stay honest rather than implicitly look formally verified.
_PRE_WORKFLOW_RATIONALE = (
    "pre-workflow: this version reached ACTIVE before the verify()/"
    "activate() approval workflow existed, via the old unrestricted "
    "PATCH. Backfilled by migration f1a2b3c4d5e6 - never formally "
    "verified by a REGULATORY_KNOWLEDGE_LEAD holder."
)

_BACKFILL_TABLES = [
    ("requirement_versions", "requirement_version"),
    ("rule_versions", "rule_version"),
    ("source_versions", "source_version"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('content_version_transitions',
    sa.Column('content_type', sa.String(length=30), nullable=False),
    sa.Column('content_version_id', sa.UUID(), nullable=False),
    sa.Column('from_status', sa.String(length=30), nullable=True),
    sa.Column('to_status', sa.String(length=30), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_content_version_transitions_content', 'content_version_transitions', ['content_type', 'content_version_id'], unique=False)
    op.create_index('ix_content_version_transitions_actor_user_id', 'content_version_transitions', ['actor_user_id'], unique=False)

    # Data migration: every version already sitting at ACTIVE reached
    # that status via the old unrestricted PATCH, with no formal
    # verify()/activate() ever recorded. Per the decision in CLAUDE.md
    # "Regulatory content approval workflow", these are NOT silently
    # grandfathered - each gets one explicit "pre-workflow" transition
    # row (actor_user_id NULL - no real approver to attribute it to) so
    # their provenance honestly shows they were never formally verified,
    # rather than looking indistinguishable from content that went
    # through the real workflow.
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    for table_name, content_type in _BACKFILL_TABLES:
        rows = bind.execute(
            sa.text(f"SELECT id FROM {table_name} WHERE status = 'ACTIVE'"),
        ).fetchall()

        for (content_version_id,) in rows:
            bind.execute(
                sa.text(
                    "INSERT INTO content_version_transitions "
                    "(id, content_type, content_version_id, from_status, to_status, "
                    "actor_user_id, rationale, created_at, updated_at) "
                    "VALUES (:id, :content_type, :content_version_id, NULL, 'ACTIVE', "
                    "NULL, :rationale, :now, :now)",
                ),
                {
                    "id": uuid.uuid4(),
                    "content_type": content_type,
                    "content_version_id": content_version_id,
                    "rationale": _PRE_WORKFLOW_RATIONALE,
                    "now": now,
                },
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_content_version_transitions_actor_user_id', table_name='content_version_transitions')
    op.drop_index('ix_content_version_transitions_content', table_name='content_version_transitions')
    op.drop_table('content_version_transitions')
