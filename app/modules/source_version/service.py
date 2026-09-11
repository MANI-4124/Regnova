from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.content_review.service import ContentReviewWorkflow
from app.modules.source.exceptions import SourceNotFound
from app.modules.source.repository import SourceRepository

from .exceptions import SourceVersionNotFound
from .models import SourceVersion, SourceVersionStatus
from .repository import SourceVersionRepository
from .schemas import (
    SourceVersionCreate,
    SourceVersionUpdate,
)

CONTENT_TYPE = "source_version"


class SourceVersionService:
    """
    Source version service. Draft/verify/activate/reject delegate to
    ContentReviewWorkflow (shared with RequirementVersion/RuleVersion) -
    see CLAUDE.md "Regulatory content approval workflow".
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = SourceVersionRepository(db)
        self.sources = SourceRepository(db)
        self.workflow = ContentReviewWorkflow(
            db, content_type=CONTENT_TYPE, status_enum=SourceVersionStatus,
        )

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

    def get_by_id_only(self, version_id: UUID) -> SourceVersion:
        """
        Unscoped - no source_id needed. See
        RequirementVersionService.get_by_id_only and CLAUDE.md
        "Ask RegNova".
        """
        version = self.repository.get_by_id_only(version_id)

        if version is None:
            raise SourceVersionNotFound()

        return version

    def create(
        self,
        source_id: UUID,
        payload: SourceVersionCreate,
        *,
        author_user_id: UUID,
    ) -> SourceVersion:
        self._get_source_or_404(source_id)

        data = payload.model_dump(exclude_unset=True)

        version = SourceVersion(
            source_id=source_id,
            author_user_id=author_user_id,
            **data,
        )

        self.repository.create(version)
        self.workflow.draft(version, actor_user_id=author_user_id)
        self.db.commit()

        return version

    def update(
        self,
        source_id: UUID,
        version_id: UUID,
        payload: SourceVersionUpdate,
    ) -> SourceVersion:
        version = self.get_by_id(source_id, version_id)
        self.workflow.require_editable(version)

        data = payload.model_dump(exclude_unset=True)

        for field, value in data.items():
            setattr(version, field, value)

        self.repository.update(version)
        self.db.commit()

        return version

    def submit_for_review(
        self,
        source_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> SourceVersion:
        version = self.get_by_id(source_id, version_id)
        self.workflow.submit_for_review(version, actor_user_id=actor_user_id)
        self.db.commit()

        return version

    def verify(
        self,
        source_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> SourceVersion:
        version = self.get_by_id(source_id, version_id)
        self.workflow.verify(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version

    def activate(
        self,
        source_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> SourceVersion:
        version = self.get_by_id(source_id, version_id)
        self.workflow.activate(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version

    def reject(
        self,
        source_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> SourceVersion:
        version = self.get_by_id(source_id, version_id)
        self.workflow.reject(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version
