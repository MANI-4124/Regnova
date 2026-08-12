from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import RegulatoryBasisRelease, RegulatoryBasisReleaseStatus


class RegulatoryBasisReleaseRepository(BaseRepository[RegulatoryBasisRelease]):
    """
    Repository for RegulatoryBasisRelease. Not organization-scoped -
    same shared platform reference data as Source/Requirement/Rule.
    """

    def __init__(self, db: Session):
        super().__init__(db, RegulatoryBasisRelease)

    def get_all(self) -> list[RegulatoryBasisRelease]:
        statement = select(RegulatoryBasisRelease).order_by(
            RegulatoryBasisRelease.created_at.desc(),
        )
        return list(self.db.scalars(statement))

    def get_active_for_jurisdiction(
        self,
        jurisdiction: str,
        market: str,
    ) -> RegulatoryBasisRelease | None:
        statement = select(RegulatoryBasisRelease).where(
            RegulatoryBasisRelease.jurisdiction == jurisdiction,
            RegulatoryBasisRelease.market == market,
            RegulatoryBasisRelease.status == RegulatoryBasisReleaseStatus.ACTIVE.value,
        )
        return self.db.scalar(statement)
