from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import SourceNotFound
from .models import Source
from .repository import SourceRepository
from .schemas import SourceResponse


class SourceService:
    """
    Business logic for Source.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = SourceRepository(db)

    def get_all(self) -> list[SourceResponse]:
        sources = self.repository.get_all()

        return [
            SourceResponse.model_validate(source)
            for source in sources
        ]

    def get_by_id(self, source_id: UUID) -> SourceResponse:
        source = self.repository.get_by_id(source_id)

        if source is None:
            raise SourceNotFound()

        return SourceResponse.model_validate(source)

    def create(self) -> SourceResponse:
        source = Source()

        self.repository.create(source)
        self.db.commit()

        return SourceResponse.model_validate(source)
