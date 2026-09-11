from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import ProductMarketState, ProductMarketStateStatus


class ProductMarketStateRepository(BaseRepository[ProductMarketState]):
    """
    Repository for ProductMarketState. Organization-scoped, like
    Product/User/Role - unlike the regulatory-content family
    (Source/Requirement/Rule/RegulatoryBasisRelease), this is customer
    data.
    """

    def __init__(self, db: Session):
        super().__init__(db, ProductMarketState)

    def get_all(
        self,
        organization_id: UUID,
        product_id: UUID,
        market: str | None = None,
    ) -> list[ProductMarketState]:
        statement = select(ProductMarketState).where(
            ProductMarketState.organization_id == organization_id,
            ProductMarketState.product_id == product_id,
        )

        if market is not None:
            statement = statement.where(ProductMarketState.market == market)

        statement = statement.order_by(ProductMarketState.created_at.desc())

        return list(self.db.scalars(statement))

    def get_all_for_organization(
        self,
        organization_id: UUID,
        gate: str | None = None,
    ) -> list[ProductMarketState]:
        """
        Org-wide, no product_id - Ask RegNova's PRODUCTS_BY_GATE intent
        (see CLAUDE.md "Ask RegNova") counts/lists across the whole
        portfolio, unlike get_all above which is scoped to one product.
        """
        statement = select(ProductMarketState).where(
            ProductMarketState.organization_id == organization_id,
        )

        if gate is not None:
            statement = statement.where(ProductMarketState.gate == gate)

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        product_id: UUID,
        state_id: UUID,
    ) -> ProductMarketState | None:
        statement = select(ProductMarketState).where(
            ProductMarketState.id == state_id,
            ProductMarketState.organization_id == organization_id,
            ProductMarketState.product_id == product_id,
        )

        return self.db.scalar(statement)

    def get_by_id_only(
        self,
        organization_id: UUID,
        state_id: UUID,
    ) -> ProductMarketState | None:
        """
        Org-scoped lookup by id alone, no product_id - used by finding
        and assessment_run, which only ever receive
        product_market_state_id (flat routes), not the parent product_id.
        """
        statement = select(ProductMarketState).where(
            ProductMarketState.id == state_id,
            ProductMarketState.organization_id == organization_id,
        )

        return self.db.scalar(statement)

    def get_active_for_product_jurisdiction(
        self,
        organization_id: UUID,
        product_id: UUID,
        jurisdiction: str,
    ) -> ProductMarketState | None:
        """
        Renamed from get_active_for_product_market by the category-
        scoping fix (see CLAUDE.md "Category scoping") - jurisdiction is
        now the real uniqueness/pinning key (see
        uq_pms_active_per_product_jurisdiction), market is kept only as
        a non-authoritative field.
        """

        statement = select(ProductMarketState).where(
            ProductMarketState.organization_id == organization_id,
            ProductMarketState.product_id == product_id,
            ProductMarketState.jurisdiction == jurisdiction,
            ProductMarketState.status == ProductMarketStateStatus.ACTIVE.value,
        )

        return self.db.scalar(statement)
