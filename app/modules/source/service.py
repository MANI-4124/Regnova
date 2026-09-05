from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import SourceNotFound
from .models import Source
from .repository import SourceRepository
from .schemas import SourceCreate, SourceResponse, SourceUpdate


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

    def create(self, payload: SourceCreate) -> SourceResponse:
        source = Source(human_reference=payload.human_reference)

        self.repository.create(source)
        self.db.commit()

        return SourceResponse.model_validate(source)

    def update(self, source_id: UUID, payload: SourceUpdate) -> SourceResponse:
        source = self.repository.get_by_id(source_id)

        if source is None:
            raise SourceNotFound()

        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(source, field, value)

        self.repository.update(source)
        self.db.commit()

        return SourceResponse.model_validate(source)
