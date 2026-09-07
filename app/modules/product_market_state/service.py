from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.product.exceptions import ProductNotFound
from app.modules.product.repository import ProductRepository
from app.modules.product_version.exceptions import ProductVersionNotFound
from app.modules.product_version.repository import ProductVersionRepository
from app.modules.regulatory_basis_release.exceptions import (
    RegulatoryBasisReleaseNotFound,
)
from app.modules.regulatory_basis_release.repository import (
    RegulatoryBasisReleaseRepository,
)
from app.modules.state_snapshot.repository import StateSnapshotRepository

from .exceptions import (
    ProductMarketStateAlreadyActive,
    ProductMarketStateIneligibleProductVersion,
    ProductMarketStateNotFound,
)
from .models import ProductMarketState
from .repository import ProductMarketStateRepository
from .schemas import (
    ProductMarketStateCreate,
    ProductMarketStateUpdate,
)


class ProductMarketStateService:
    """
    Business logic for ProductMarketState.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = ProductMarketStateRepository(db)
        self.products = ProductRepository(db)
        self.product_versions = ProductVersionRepository(db)
        self.releases = RegulatoryBasisReleaseRepository(db)
        self.state_snapshots = StateSnapshotRepository(db)

    def _get_product_or_404(self, organization_id: UUID, product_id: UUID):
        product = self.products.get_by_id(organization_id, product_id)

        if product is None:
            raise ProductNotFound()

        return product

    def _validate_product_version(
        self,
        organization_id: UUID,
        product_id: UUID,
        product_version_id: UUID,
    ):
        version = self.product_versions.get_by_id(
            organization_id,
            product_id,
            product_version_id,
        )

        if version is None:
            raise ProductVersionNotFound()

        if not version.is_active:
            raise ProductMarketStateIneligibleProductVersion()

        return version

    def get_all(
        self,
        organization_id: UUID,
        product_id: UUID,
        market: str | None = None,
    ) -> list[ProductMarketState]:
        self._get_product_or_404(organization_id, product_id)

        return self.repository.get_all(organization_id, product_id, market)

    def get_by_id(
        self,
        organization_id: UUID,
        product_id: UUID,
        state_id: UUID,
    ) -> ProductMarketState:
        self._get_product_or_404(organization_id, product_id)

        state = self.repository.get_by_id(organization_id, product_id, state_id)

        if state is None:
            raise ProductMarketStateNotFound()

        return state

    def create(
        self,
        organization_id: UUID,
        product_id: UUID,
        payload: ProductMarketStateCreate,
        actor_user_id: UUID | None = None,
    ) -> ProductMarketState:
        self._get_product_or_404(organization_id, product_id)

        # AC-FR-03-01: duplicate requests return the same active state,
        # not an error or a second row - and not a silent pointer update
        # if the request's product_version_id differs from the existing
        # row's.
        existing = self.repository.get_active_for_product_jurisdiction(
            organization_id,
            product_id,
            payload.jurisdiction,
        )
        if existing is not None:
            return existing

        version = self._validate_product_version(
            organization_id,
            product_id,
            payload.product_version_id,
        )

        # Auto-pin resolution key, post category-scoping fix (see
        # CLAUDE.md "Category scoping"): jurisdiction from the payload
        # + the pinned product version's own category - not `market`,
        # which is kept only as a non-authoritative field.
        release = self.releases.get_active_for_jurisdiction_and_category(
            payload.jurisdiction,
            version.category,
        )

        state = ProductMarketState(
            organization_id=organization_id,
            product_id=product_id,
            product_version_id=version.id,
            market=payload.market,
            jurisdiction=payload.jurisdiction,
            regulatory_basis_release_id=release.id if release else None,
            created_by_user_id=actor_user_id,
        )

        try:
            self.repository.create(state)
            self.db.commit()
        except IntegrityError:
            # Race: another request created the active state between our
            # check above and this insert. The partial unique index
            # caught it - resolve the same way AC-FR-03-01 asks for.
            self.db.rollback()

            existing = self.repository.get_active_for_product_jurisdiction(
                organization_id,
                product_id,
                payload.jurisdiction,
            )
            if existing is not None:
                return existing

            raise

        return state

    def update(
        self,
        organization_id: UUID,
        product_id: UUID,
        state_id: UUID,
        payload: ProductMarketStateUpdate,
    ) -> ProductMarketState:
        state = self.get_by_id(organization_id, product_id, state_id)

        if payload.product_version_id is not None:
            self._validate_product_version(
                organization_id,
                product_id,
                payload.product_version_id,
            )

        if payload.regulatory_basis_release_id is not None:
            if self.releases.get_by_id(payload.regulatory_basis_release_id) is None:
                raise RegulatoryBasisReleaseNotFound()

        # Minimal half of staleness (see CLAUDE.md "Market readiness" -
        # resolution: both halves in scope, cascading impact analysis
        # stays out): a direct, synchronous flag the moment the pin
        # actually changes, in the SAME transaction as the update -
        # not a background job, and not walking dependency edges to
        # figure out exactly which Requirement Results/Findings are
        # affected (C11, unbuilt).
        pin_changed = (
            payload.product_version_id is not None
            and payload.product_version_id != state.product_version_id
        ) or (
            payload.regulatory_basis_release_id is not None
            and payload.regulatory_basis_release_id != state.regulatory_basis_release_id
        )

        data = payload.model_dump(exclude_unset=True)

        for field, value in data.items():
            setattr(state, field, value)

        if pin_changed:
            current_snapshot = self.state_snapshots.get_current(state.id)
            if current_snapshot is not None:
                current_snapshot.is_current = False
                current_snapshot.stale_reason = "PRODUCT_MARKET_STATE_PIN_CHANGED"
                self.state_snapshots.update(current_snapshot)

        try:
            self.repository.update(state)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ProductMarketStateAlreadyActive()

        return state
