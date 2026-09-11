from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import AskRegnovaQuery


class AskRegnovaQueryRepository(BaseRepository[AskRegnovaQuery]):
    """
    Repository for AskRegnovaQuery. Organization-scoped, like Finding/
    ProductMarketState - customer data, not the regulatory-content
    family.
    """

    def __init__(self, db: Session):
        super().__init__(db, AskRegnovaQuery)

    def get_all(
        self,
        organization_id: UUID,
    ) -> list[AskRegnovaQuery]:
        statement = (
            select(AskRegnovaQuery)
            .where(AskRegnovaQuery.organization_id == organization_id)
            .order_by(AskRegnovaQuery.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        query_id: UUID,
    ) -> AskRegnovaQuery | None:
        statement = select(AskRegnovaQuery).where(
            AskRegnovaQuery.id == query_id,
            AskRegnovaQuery.organization_id == organization_id,
        )

        return self.db.scalar(statement)
