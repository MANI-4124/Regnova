from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import StateSnapshot


class StateSnapshotRepository(BaseRepository[StateSnapshot]):
    """
    Repository for StateSnapshot. Organization-scoped, like Finding/
    AssessmentRun (customer-visible readiness data), not the
    regulatory-content family.
    """

    def __init__(self, db: Session):
        super().__init__(db, StateSnapshot)

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[StateSnapshot]:
        statement = (
            select(StateSnapshot)
            .where(
                StateSnapshot.organization_id == organization_id,
                StateSnapshot.product_market_state_id == product_market_state_id,
            )
            .order_by(StateSnapshot.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        snapshot_id: UUID,
    ) -> StateSnapshot | None:
        statement = select(StateSnapshot).where(
            StateSnapshot.id == snapshot_id,
            StateSnapshot.organization_id == organization_id,
            StateSnapshot.product_market_state_id == product_market_state_id,
        )

        return self.db.scalar(statement)

    def get_current(self, product_market_state_id: UUID) -> StateSnapshot | None:
        statement = (
            select(StateSnapshot)
            .where(
                StateSnapshot.product_market_state_id == product_market_state_id,
                StateSnapshot.is_current.is_(True),
            )
            .order_by(StateSnapshot.created_at.desc())
            .limit(1)
        )

        return self.db.scalar(statement)
