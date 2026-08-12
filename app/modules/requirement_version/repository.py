from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import RequirementVersion


class RequirementVersionRepository(BaseRepository[RequirementVersion]):
    """
    Repository for RequirementVersion. Scoped by requirement_id
    (parent-child integrity), not organization_id.
    """

    def __init__(self, db: Session):
        super().__init__(db, RequirementVersion)

    def get_all(self, requirement_id: UUID) -> list[RequirementVersion]:
        statement = (
            select(RequirementVersion)
            .where(RequirementVersion.requirement_id == requirement_id)
            .order_by(RequirementVersion.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        requirement_id: UUID,
        version_id: UUID,
    ) -> RequirementVersion | None:
        statement = (
            select(RequirementVersion)
            .where(
                RequirementVersion.id == version_id,
                RequirementVersion.requirement_id == requirement_id,
            )
        )

        return self.db.scalar(statement)

    def get_by_id_only(self, version_id: UUID) -> RequirementVersion | None:
        """
        Unscoped lookup by id alone - used by rule_version, which only
        ever receives requirement_version_id, not the parent
        requirement_id.
        """
        return super().get_by_id(version_id)
