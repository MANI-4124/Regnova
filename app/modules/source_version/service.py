from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.source.exceptions import SourceNotFound
from app.modules.source.repository import SourceRepository

from .exceptions import SourceVersionNotFound
from .models import SourceVersion
from .repository import SourceVersionRepository
from .schemas import (
    SourceVersionCreate,
    SourceVersionUpdate,
)


class SourceVersionService:
    """
    Source version service.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = SourceVersionRepository(db)
        self.sources = SourceRepository(db)

    def _get_source_or_404(self, source_id: UUID):
        source = self.sources.get_by_id(source_id)

        if source is None:
            raise SourceNotFound()

        return source

    def get_all(self, source_id: UUID) -> list[SourceVersion]:
        self._get_source_or_404(source_id)

        return self.repository.get_all(source_id)

    def get_by_id(
        self,
        source_id: UUID,
        version_id: UUID,
    ) -> SourceVersion:
        self._get_source_or_404(source_id)

        version = self.repository.get_by_id(source_id, version_id)

        if version is None:
            raise SourceVersionNotFound()

        return version

    def create(
        self,
        source_id: UUID,
        payload: SourceVersionCreate,
    ) -> SourceVersion:
        self._get_source_or_404(source_id)

        data = payload.model_dump(exclude_unset=True)

        version = SourceVersion(
            source_id=source_id,
            **data,
        )

        self.repository.create(version)
        self.db.commit()

        return version

    def update(
        self,
        source_id: UUID,
        version_id: UUID,
        payload: SourceVersionUpdate,
    ) -> SourceVersion:
        version = self.get_by_id(source_id, version_id)

        data = payload.model_dump(exclude_unset=True)

        for field, value in data.items():
            setattr(version, field, value)

        self.repository.update(version)
        self.db.commit()

        return version
