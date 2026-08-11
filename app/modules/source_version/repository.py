from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import SourceVersion


class SourceVersionRepository(BaseRepository[SourceVersion]):
    """
    Repository for SourceVersion. Scoped by source_id (parent-child
    integrity), not organization_id - Source content has no tenant.
    """

    def __init__(self, db: Session):
        super().__init__(db, SourceVersion)

    def get_all(self, source_id: UUID) -> list[SourceVersion]:
        statement = (
            select(SourceVersion)
            .where(SourceVersion.source_id == source_id)
            .order_by(SourceVersion.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        source_id: UUID,
        version_id: UUID,
    ) -> SourceVersion | None:
        statement = (
            select(SourceVersion)
            .where(
                SourceVersion.id == version_id,
                SourceVersion.source_id == source_id,
            )
        )

        return self.db.scalar(statement)

    def get_by_id_only(self, version_id: UUID) -> SourceVersion | None:
        """
        Unscoped lookup by id alone - used by source_location, which is
        a flat resource that only ever receives source_version_id, not
        the parent source_id.
        """
        return super().get_by_id(version_id)
