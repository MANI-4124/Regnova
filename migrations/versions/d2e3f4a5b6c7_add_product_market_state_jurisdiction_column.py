"""add_product_market_state_jurisdiction_column

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-07 00:00:01.000000

Adds ProductMarketState.jurisdiction (NOT NULL) and moves the partial
unique index from (organization_id, product_id, market) to
(organization_id, product_id, jurisdiction) - see CLAUDE.md "Category
scoping". `market` is kept as a non-authoritative column, its long-term
fate an open question this migration does not resolve.

Backfill is a straight `jurisdiction = market` copy for every existing
row, not a TESTLAND-specific heuristic like the sibling
product_versions.category migration: pre-fix, every caller of
ProductMarketStateService.create() already passed the same value for
both the jurisdiction and market arguments of the release-resolution
lookup (see the removed get_active_for_jurisdiction(market, market)
call), so an existing row's own `market` value already *is* what would
have been used as jurisdiction. This is exact, not a heuristic guess -
there is no equivalent "little else to classify" judgment call needed
here.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('uq_pms_active_per_product_market', table_name='product_market_states')

    op.add_column('product_market_states', sa.Column('jurisdiction', sa.String(length=100), nullable=True))
    op.execute(sa.text(
        "UPDATE product_market_states SET jurisdiction = market WHERE jurisdiction IS NULL",
    ))
    op.alter_column('product_market_states', 'jurisdiction', nullable=False)

    op.create_index('ix_pms_jurisdiction', 'product_market_states', ['jurisdiction'], unique=False)
    op.create_index(
        'uq_pms_active_per_product_jurisdiction',
        'product_market_states',
        ['organization_id', 'product_id', 'jurisdiction'],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_pms_active_per_product_jurisdiction', table_name='product_market_states')
    op.drop_index('ix_pms_jurisdiction', table_name='product_market_states')
    op.drop_column('product_market_states', 'jurisdiction')
    op.create_index(
        'uq_pms_active_per_product_market',
        'product_market_states',
        ['organization_id', 'product_id', 'market'],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
