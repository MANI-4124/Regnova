from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import SourceLocation


class SourceLocationRepository(BaseRepository[SourceLocation]):
    """
    Repository for SourceLocation - a flat resource, optionally filtered
    by source_version_id. get_by_id is the inherited unscoped
    BaseRepository method (location ids are globally unique; there is no
    tenant boundary to enforce here).
    """

    def __init__(self, db: Session):
        super().__init__(db, SourceLocation)

    def get_all(
        self,
        source_version_id: UUID | None = None,
    ) -> list[SourceLocation]:
        statement = select(SourceLocation).order_by(
            SourceLocation.created_at.asc()
        )

        if source_version_id is not None:
            statement = statement.where(
                SourceLocation.source_version_id == source_version_id
            )

        return list(self.db.scalars(statement))
