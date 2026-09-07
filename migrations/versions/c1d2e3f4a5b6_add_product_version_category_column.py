"""add_product_version_category_column

Revision ID: c1d2e3f4a5b6
Revises: b3c4d5e6f7a8
Create Date: 2026-09-07 00:00:00.000000

Adds ProductVersion.category (NOT NULL) - the category-scoping fix, see
CLAUDE.md "Category scoping". Added nullable first, backfilled, then
constrained NOT NULL rather than a straight NOT NULL add, in case a real
deployment already has product_versions rows: resolution was option (b)
(NULL not allowed past this migration, not a nullable-forever column or
a silently-tolerated sentinel) on the grounds that the only content this
schema realistically holds pre-migration is the synthetic TESTLAND
corpus, which is mechanically backfillable from its own known
(pre-fix) ProductMarketState.market naming convention
("TESTLAND-BEAUTY"/"TESTLAND-NUTRA"/"TESTLAND-MEDDEVICE") - there is
"little else to classify". Anything that doesn't match that convention
(a hand-created dev/test row) falls back to 'UNCLASSIFIED', which is
never a value new code writes going forward (ProductVersionCreate.category
is required, no default) - it only ever marks a pre-existing row this
migration couldn't classify from data alone, flagging it for manual
follow-up rather than guessing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('product_versions', sa.Column('category', sa.String(length=100), nullable=True))

    op.execute(sa.text("""
        UPDATE product_versions
        SET category = COALESCE(
            (
                SELECT CASE pms.market
                    WHEN 'TESTLAND-BEAUTY' THEN 'Beauty'
                    WHEN 'TESTLAND-NUTRA' THEN 'Nutraceuticals'
                    WHEN 'TESTLAND-MEDDEVICE' THEN 'Medical Devices'
                    ELSE NULL
                END
                FROM product_market_states pms
                WHERE pms.product_version_id = product_versions.id
                LIMIT 1
            ),
            'UNCLASSIFIED'
        )
        WHERE category IS NULL
    """))

    op.alter_column('product_versions', 'category', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('product_versions', 'category')
