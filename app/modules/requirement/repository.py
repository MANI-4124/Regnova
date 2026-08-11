from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Requirement


class RequirementRepository(BaseRepository[Requirement]):
    """
    Repository for Requirement. Not organization-scoped - Requirement is
    shared platform reference data, same as Source.
    """

    def __init__(self, db: Session):
        super().__init__(db, Requirement)

    def get_all(self) -> list[Requirement]:
        statement = select(Requirement).order_by(Requirement.created_at.desc())
        return list(self.db.scalars(statement))
