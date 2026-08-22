from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import StateSnapshotNotFound
from .models import StateSnapshot
from .repository import StateSnapshotRepository


class StateSnapshotService:
    """
    Read-only service - StateSnapshot rows are only ever created by
    MarketReadinessService, same "no write endpoints, system-produced"
    shape as Finding.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = StateSnapshotRepository(db)

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[StateSnapshot]:
        return self.repository.get_all(organization_id, product_market_state_id)

    def get_by_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        snapshot_id: UUID,
    ) -> StateSnapshot:
        snapshot = self.repository.get_by_id(
            organization_id,
            product_market_state_id,
            snapshot_id,
        )

        if snapshot is None:
            raise StateSnapshotNotFound()

        return snapshot
