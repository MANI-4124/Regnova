from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.content_review.service import ContentReviewWorkflow
from app.modules.requirement_version.exceptions import RequirementVersionNotFound
from app.modules.requirement_version.repository import RequirementVersionRepository
from app.modules.rule.exceptions import RuleNotFound
from app.modules.rule.repository import RuleRepository
from app.modules.source_location.exceptions import SourceLocationNotFound
from app.modules.source_location.repository import SourceLocationRepository

from .exceptions import RuleVersionNotFound
from .models import RuleVersion, RuleVersionStatus
from .repository import RuleVersionRepository
from .schemas import (
    RuleVersionCreate,
    RuleVersionUpdate,
)

CONTENT_TYPE = "rule_version"


class RuleVersionService:
    """
    Rule version service. Draft/verify/activate/reject delegate to
    ContentReviewWorkflow (shared with RequirementVersion/SourceVersion)
    - see CLAUDE.md "Regulatory content approval workflow".
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = RuleVersionRepository(db)
        self.rules = RuleRepository(db)
        self.requirement_versions = RequirementVersionRepository(db)
        self.source_locations = SourceLocationRepository(db)
        self.workflow = ContentReviewWorkflow(
            db, content_type=CONTENT_TYPE, status_enum=RuleVersionStatus,
        )

    def _get_rule_or_404(self, rule_id: UUID):
        rule = self.rules.get_by_id(rule_id)

        if rule is None:
            raise RuleNotFound()

        return rule

    def _validate_requirement_version(
        self,
        requirement_version_id: UUID | None,
    ) -> None:
        if requirement_version_id is None:
            return

        version = self.requirement_versions.get_by_id_only(
            requirement_version_id,
        )

        if version is None:
            raise RequirementVersionNotFound()

    def _resolve_source_locations(self, source_location_ids: list[UUID]):
        locations = []

        for location_id in source_location_ids:
            location = self.source_locations.get_by_id(location_id)

            if location is None:
                raise SourceLocationNotFound()

            locations.append(location)

        return locations

    def get_all(self, rule_id: UUID) -> list[RuleVersion]:
        self._get_rule_or_404(rule_id)

        return self.repository.get_all(rule_id)

    def get_by_id(self, rule_id: UUID, version_id: UUID) -> RuleVersion:
        self._get_rule_or_404(rule_id)

        version = self.repository.get_by_id(rule_id, version_id)

        if version is None:
            raise RuleVersionNotFound()

        return version

    def get_by_id_only(self, version_id: UUID) -> RuleVersion:
        """
        Unscoped - no rule_id needed. See RequirementVersionService's
        own get_by_id_only and CLAUDE.md "Ask RegNova".
        """
        version = self.repository.get_by_id_only(version_id)

        if version is None:
            raise RuleVersionNotFound()

        return version

    def create(
        self,
        rule_id: UUID,
        payload: RuleVersionCreate,
        *,
        author_user_id: UUID,
    ) -> RuleVersion:
        self._get_rule_or_404(rule_id)
        self._validate_requirement_version(payload.requirement_version_id)

        data = payload.model_dump(
            exclude_unset=True,
            exclude={"source_location_ids"},
        )

        version = RuleVersion(
            rule_id=rule_id,
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
        rule_id: UUID,
        version_id: UUID,
        payload: RuleVersionUpdate,
    ) -> RuleVersion:
        version = self.get_by_id(rule_id, version_id)
        self.workflow.require_editable(version)

        if "requirement_version_id" in payload.model_fields_set:
            self._validate_requirement_version(
                payload.requirement_version_id,
            )

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
        rule_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
    ) -> RuleVersion:
        version = self.get_by_id(rule_id, version_id)
        self.workflow.submit_for_review(version, actor_user_id=actor_user_id)
        self.db.commit()

        return version

    def verify(
        self,
        rule_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> RuleVersion:
        version = self.get_by_id(rule_id, version_id)
        self.workflow.verify(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version

    def activate(
        self,
        rule_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> RuleVersion:
        version = self.get_by_id(rule_id, version_id)
        self.workflow.activate(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version

    def reject(
        self,
        rule_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID,
        rationale: str,
    ) -> RuleVersion:
        version = self.get_by_id(rule_id, version_id)
        self.workflow.reject(version, actor_user_id=actor_user_id, rationale=rationale)
        self.db.commit()

        return version
