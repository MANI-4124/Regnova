"""add_organization_is_synthetic_column

Revision ID: d1e2f3a4b5c6
Revises: c8a1f2b3d4e5
Create Date: 2026-09-12 09:00:00.000000

The real gate the free-tier Gemini warnings across app/analysis/,
app/extraction/, and app/query_classification/ have all along said was
"logged, not built": Organization.is_synthetic. Additive, nullable-free
with a safe default (every existing row becomes non-synthetic, the
conservative default - a real customer org must never retroactively gain
AI-hop eligibility from a schema change alone). Never settable via the
Create/Update API - see organization/schemas.py, unchanged by this
migration - only a direct DB/seed operation (scripts/seed_testland_corpus.py)
sets it, same "structural, not API-driven" principle as is_internal.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c8a1f2b3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'organizations',
        sa.Column('is_synthetic', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Drop the server_default after backfilling existing rows - matches
    # this codebase's own convention elsewhere for NOT NULL columns added
    # to an already-populated table (compute a safe value for existing
    # rows, then make the column's Python-side default the only default
    # going forward, not a standing DB-level one).
    op.alter_column('organizations', 'is_synthetic', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('organizations', 'is_synthetic')
