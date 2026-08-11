from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.source_version.exceptions import SourceVersionNotFound
from app.modules.source_version.repository import SourceVersionRepository

from .exceptions import SourceLocationNotFound
from .models import SourceLocation
from .repository import SourceLocationRepository
from .schemas import (
    SourceLocationCreate,
    SourceLocationUpdate,
)


class SourceLocationService:
    """
    Source location service. Flat resource - only ever knows
    source_version_id, not a parent source_id.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = SourceLocationRepository(db)
        self.source_versions = SourceVersionRepository(db)

    def _get_source_version_or_404(self, source_version_id: UUID):
        version = self.source_versions.get_by_id_only(source_version_id)

        if version is None:
            raise SourceVersionNotFound()

        return version

    def get_all(
        self,
        source_version_id: UUID | None = None,
    ) -> list[SourceLocation]:
        if source_version_id is not None:
            self._get_source_version_or_404(source_version_id)

        return self.repository.get_all(source_version_id)

    def get_by_id(self, location_id: UUID) -> SourceLocation:
        location = self.repository.get_by_id(location_id)

        if location is None:
            raise SourceLocationNotFound()

        return location

    def create(self, payload: SourceLocationCreate) -> SourceLocation:
        self._get_source_version_or_404(payload.source_version_id)

        data = payload.model_dump(exclude_unset=True)

        location = SourceLocation(**data)

        self.repository.create(location)
        self.db.commit()

        return location

    def update(
        self,
        location_id: UUID,
        payload: SourceLocationUpdate,
    ) -> SourceLocation:
        location = self.get_by_id(location_id)

        data = payload.model_dump(exclude_unset=True)

        for field, value in data.items():
            setattr(location, field, value)

        self.repository.update(location)
        self.db.commit()

        return location
