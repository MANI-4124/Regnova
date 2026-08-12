from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import RuleVersion


class RuleVersionRepository(BaseRepository[RuleVersion]):
    """
    Repository for RuleVersion. Scoped by rule_id (parent-child
    integrity), not organization_id.
    """

    def __init__(self, db: Session):
        super().__init__(db, RuleVersion)

    def get_all(self, rule_id: UUID) -> list[RuleVersion]:
        statement = (
            select(RuleVersion)
            .where(RuleVersion.rule_id == rule_id)
            .order_by(RuleVersion.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        rule_id: UUID,
        version_id: UUID,
    ) -> RuleVersion | None:
        statement = (
            select(RuleVersion)
            .where(
                RuleVersion.id == version_id,
                RuleVersion.rule_id == rule_id,
            )
        )

        return self.db.scalar(statement)
