from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.content_review.service import ContentReviewWorkflow
from app.modules.requirement.exceptions import RequirementNotFound
from app.modules.requirement.repository import RequirementRepository
from app.modules.source_location.exceptions import SourceLocationNotFound
from app.modules.source_location.repository import SourceLocationRepository

from .exceptions import RequirementVersionNotFound
from .models import RequirementVersion, RequirementVersionStatus
from .repository import RequirementVersionRepository
from .schemas import (
    RequirementVersionCreate,
    RequirementVersionUpdate,
)

CONTENT_TYPE = "requirement_version"


class RequirementVersionService:
    """
    Requirement version service. Draft/verify/activate/reject delegate
    to ContentReviewWorkflow (shared with RuleVersion/SourceVersion) -
    see CLAUDE.md "Regulatory content approval workflow".
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = RequirementVersionRepository(db)
        self.requirements = RequirementRepository(db)
        self.source_locations = SourceLocationRepository(db)
        self.workflow = ContentReviewWorkflow(
            db, content_type=CONTENT_TYPE, status_enum=RequirementVersionStatus,
        )

    def _get_requirement_or_404(self, requirement_id: UUID):
        requirement = self.requirements.get_by_id(requirement_id)

        if requirement is None:
            raise RequirementNotFound()

        return requirement

    def _resolve_source_locations(self, source_location_ids: list[UUID]):
        locations = []

        for location_id in source_location_ids:
            location = self.source_locations.get_by_id(location_id)

            if location is None:
                raise SourceLocationNotFound()

            locations.append(location)

        return locations

    def get_all(self, requirement_id: UUID) -> list[RequirementVersion]:
        self._get_requirement_or_404(requirement_id)

        return self.repository.get_all(requirement_id)

    def get_by_id(
        self,
        requirement_id: UUID,
        version_id: UUID,
    ) -> RequirementVersion:
        self._get_requirement_or_404(requirement_id)

        version = self.repository.get_by_id(requirement_id, version_id)

        if version is None:
            raise RequirementVersionNotFound()

        return version

    def create(
        self,
        requirement_id: UUID,
        payload: RequirementVersionCreate,
        *,
        author_user_id: UUID,
    ) -> RequirementVersion:
        self._get_requirement_or_404(requirement_id)

        data = payload.model_dump(
            exclude_unset=True,
            exclude={"source_location_ids"},
        )

        version = RequirementVersion(
            requirement_id=requirement_id,
            author_user_id=author_user_id,
            **data,
        )

        if payload.source_location_ids:
            version.source_locations = self._resolve_source_locations(
                payload.source_location_ids,
            )

        self.repository.create(version)
        self.workflow.draft(version, actor_user_id=author_user_id)
        self.db.commit()

        return version

    def update(
        self,
        requirement_id: UUID,
        version_id: UUID,
        payload: RequirementVersionUpdate,
    ) -> RequirementVersion:
        version = self.get_by_id(requirement_id, version_id)
        self.workflow.require_editable(version)

        data = payload.model_dump(
            exclude_unset=True,
            exclude={"source_location_ids"},
        )

        for field, value in data.items():
            setattr(version, field, value)

        if "source_location_ids" in payload.model_fields_set:
            ids = payload.source_location_ids or []
            version.source_locations = self._resolve_source_locations(ids)

        self.repository.update(version)
        self.db.commit()

        return version

    def submit_for_review(
        self,
        requirement_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> RequirementVersion:
        version = self.get_by_id(requirement_id, version_id)
        self.workflow.submit_for_review(version, actor_user_id=actor_user_id)
        self.db.commit()

        return version

    def verify(
        self,
        requirement_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> RequirementVersion:
        version = self.get_by_id(requirement_id, version_id)
        self.workflow.verify(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version

    def activate(
        self,
        requirement_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> RequirementVersion:
        version = self.get_by_id(requirement_id, version_id)
        self.workflow.activate(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version

    def reject(
        self,
        requirement_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> RequirementVersion:
        version = self.get_by_id(requirement_id, version_id)
        self.workflow.reject(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version
