from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Source


class SourceRepository(BaseRepository[Source]):
    """
    Repository for Source. Not organization-scoped - Source is shared
    platform reference data.
    """

    def __init__(self, db: Session):
        super().__init__(db, Source)

    def get_all(self) -> list[Source]:
        statement = select(Source).order_by(Source.created_at.desc())
        return list(self.db.scalars(statement))
