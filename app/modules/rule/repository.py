from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Rule


class RuleRepository(BaseRepository[Rule]):
    """
    Repository for Rule. Not organization-scoped - Rule is shared
    platform reference data, same as Source/Requirement.
    """

    def __init__(self, db: Session):
        super().__init__(db, Rule)

    def get_all(self) -> list[Rule]:
        statement = select(Rule).order_by(Rule.created_at.desc())
        return list(self.db.scalars(statement))
