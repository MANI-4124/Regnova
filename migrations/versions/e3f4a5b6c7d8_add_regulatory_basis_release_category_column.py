"""add_regulatory_basis_release_category_column

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-07 00:00:02.000000

Adds RegulatoryBasisRelease.category (NOT NULL) - see CLAUDE.md
"Category scoping". Backfill derives category from the release's own
included requirement_versions (via the
regulatory_basis_release_requirement_versions join table): when every
included RequirementVersion shares exactly one category, that value is
used - this is a real, precise re-derivation, not a guess, since
RequirementVersion.category has existed unchanged since C5 and every
included version was already required to be ACTIVE+verified before
inclusion. A release with no requirement_versions included, or whose
included versions span more than one category (only possible for a
release created before this fix's own assembly-time category check
existed), falls back to 'UNCLASSIFIED' - flagged the same way as the
sibling product_versions.category migration's fallback, for the same
"little else to classify" reason: real content in this schema today is
exactly the single-category Malaysia/Beauty seed plus the synthetic
TESTLAND corpus, neither of which produces the multi-category case.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('regulatory_basis_releases', sa.Column('category', sa.String(length=100), nullable=True))

    op.execute(sa.text("""
        UPDATE regulatory_basis_releases
        SET category = COALESCE(
            (
                SELECT rv.category
                FROM regulatory_basis_release_requirement_versions rbrv
                JOIN requirement_versions rv ON rv.id = rbrv.requirement_version_id
                WHERE rbrv.release_id = regulatory_basis_releases.id
                GROUP BY rv.category
                HAVING COUNT(DISTINCT rv.category) = 1
                LIMIT 1
            ),
            'UNCLASSIFIED'
        )
        WHERE category IS NULL
    """))

    op.alter_column('regulatory_basis_releases', 'category', nullable=False)
    op.create_index('ix_rbr_category', 'regulatory_basis_releases', ['category'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_rbr_category', table_name='regulatory_basis_releases')
    op.drop_column('regulatory_basis_releases', 'category')
