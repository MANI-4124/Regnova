from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.repository import OutboxRepository
from app.modules.organization.repository import OrganizationRepository
from app.modules.requirement_version.exceptions import RequirementVersionNotFound
from app.modules.requirement_version.models import RequirementVersionStatus
from app.modules.requirement_version.repository import RequirementVersionRepository
from app.modules.rule_version.exceptions import RuleVersionNotFound
from app.modules.rule_version.models import RuleVersionStatus
from app.modules.rule_version.repository import RuleVersionRepository
from app.modules.source_version.exceptions import SourceVersionNotFound
from app.modules.source_version.models import SourceVersionStatus
from app.modules.source_version.repository import SourceVersionRepository

from .exceptions import (
    RegulatoryBasisReleaseAlreadyActive,
    RegulatoryBasisReleaseDuplicateContent,
    RegulatoryBasisReleaseIneligibleVersion,
    RegulatoryBasisReleaseNotFound,
    RegulatoryBasisReleaseVersionScopeMismatch,
)
from .models import RegulatoryBasisRelease, RegulatoryBasisReleaseStatus
from .repository import RegulatoryBasisReleaseRepository
from .schemas import (
    RegulatoryBasisReleaseCreate,
    RegulatoryBasisReleaseUpdate,
)


def _compute_content_hash(
    source_ids: list[UUID],
    requirement_ids: list[UUID],
    rule_ids: list[UUID],
    configuration: dict | None,
) -> str:
    payload = {
        "source_version_ids": sorted(str(i) for i in source_ids),
        "requirement_version_ids": sorted(str(i) for i in requirement_ids),
        "rule_version_ids": sorted(str(i) for i in rule_ids),
        "configuration": configuration,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RegulatoryBasisReleaseService:
    """
    Business logic for RegulatoryBasisRelease.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = RegulatoryBasisReleaseRepository(db)
        self.source_versions = SourceVersionRepository(db)
        self.requirement_versions = RequirementVersionRepository(db)
        self.rule_versions = RuleVersionRepository(db)
        self.organizations = OrganizationRepository(db)
        self.outbox = OutboxRepository(db)

    def _publish_activated(
        self,
        release: RegulatoryBasisRelease,
        *,
        previous_active_release_id,
        actor_user_id,
        correlation_id: str | None,
    ) -> None:
        """
        RegulatoryBasisRelease has no organization_id of its own - same
        problem ContentVersionTransitioned already solved (see CLAUDE.md
        "Regulatory content approval workflow"). Reuses the exact same
        fix: tenant-zero's own Organization id, silently skipped if
        tenant-zero doesn't exist yet in this environment (regulatory-
        content writes must not fail over notification plumbing).
        """
        internal_org = self.organizations.get_internal()
        if internal_org is None:
            return

        self.outbox.append(
            organization_id=internal_org.id,
            event_type="RegulatoryBasisActivated",
            schema_version=1,
            payload={
                "release_id": str(release.id),
                "jurisdiction": release.jurisdiction,
                "category": release.category,
                "previous_active_release_id": (
                    str(previous_active_release_id) if previous_active_release_id else None
                ),
                "effective_from": (
                    release.effective_from.isoformat() if release.effective_from else None
                ),
                "effective_to": (
                    release.effective_to.isoformat() if release.effective_to else None
                ),
            },
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

    def _resolve_eligible_source_versions(self, ids: list[UUID]):
        versions = []

        for version_id in ids:
            version = self.source_versions.get_by_id_only(version_id)

            if version is None:
                raise SourceVersionNotFound()

            if version.status != SourceVersionStatus.ACTIVE.value or version.verified_at is None:
                raise RegulatoryBasisReleaseIneligibleVersion()

            versions.append(version)

        return versions

    def _resolve_eligible_requirement_versions(
        self,
        ids: list[UUID],
        *,
        jurisdiction: str,
        category: str,
    ):
        versions = []

        for version_id in ids:
            version = self.requirement_versions.get_by_id_only(version_id)

            if version is None:
                raise RequirementVersionNotFound()

            if (
                version.status != RequirementVersionStatus.ACTIVE.value
                or version.verified_at is None
            ):
                raise RegulatoryBasisReleaseIneligibleVersion()

            # Bundled with the eligibility check above, not a separate
            # pass - see CLAUDE.md "Category scoping". A version that's
            # ACTIVE+verified but scoped to a different jurisdiction/
            # category has no business in this release regardless.
            if version.jurisdiction != jurisdiction or version.category != category:
                raise RegulatoryBasisReleaseVersionScopeMismatch()

            versions.append(version)

        return versions

    def _resolve_eligible_rule_versions(
        self,
        ids: list[UUID],
        *,
        jurisdiction: str,
        category: str,
    ):
        versions = []

        for version_id in ids:
            version = self.rule_versions.get_by_id_only(version_id)

            if version is None:
                raise RuleVersionNotFound()

            if version.status != RuleVersionStatus.ACTIVE.value or version.verified_at is None:
                raise RegulatoryBasisReleaseIneligibleVersion()

            # RuleVersion carries no jurisdiction/category of its own -
            # only validated transitively, via the RequirementVersion it
            # operationalizes, when one exists. A standalone rule
            # (requirement_version_id is None - C6's CALCULATION_COMPONENT
            # output type) has nothing to check against and is let
            # through unchecked - a real, named gap, not silently
            # resolved: see CLAUDE.md "Known limitations" for why this
            # can't be closed without giving RuleVersion its own
            # jurisdiction/category fields.
            if version.requirement_version_id is not None:
                linked = self.requirement_versions.get_by_id_only(
                    version.requirement_version_id,
                )
                if linked is not None and (
                    linked.jurisdiction != jurisdiction or linked.category != category
                ):
                    raise RegulatoryBasisReleaseVersionScopeMismatch()

            versions.append(version)

        return versions

    def get_all(self) -> list[RegulatoryBasisRelease]:
        return self.repository.get_all()

    def get_by_id(self, release_id: UUID) -> RegulatoryBasisRelease:
        release = self.repository.get_by_id(release_id)

        if release is None:
            raise RegulatoryBasisReleaseNotFound()

        return release

    def create(
        self,
        payload: RegulatoryBasisReleaseCreate,
        actor_user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> RegulatoryBasisRelease:
        source_versions = self._resolve_eligible_source_versions(
            payload.source_version_ids or [],
        )
        requirement_versions = self._resolve_eligible_requirement_versions(
            payload.requirement_version_ids or [],
            jurisdiction=payload.jurisdiction,
            category=payload.category,
        )
        rule_versions = self._resolve_eligible_rule_versions(
            payload.rule_version_ids or [],
            jurisdiction=payload.jurisdiction,
            category=payload.category,
        )

        if payload.supersedes_id is not None:
            if self.repository.get_by_id(payload.supersedes_id) is None:
                raise RegulatoryBasisReleaseNotFound()

        status = payload.status or RegulatoryBasisReleaseStatus.ACTIVE.value

        existing_active = None

        if status == RegulatoryBasisReleaseStatus.ACTIVE.value:
            existing_active = self.repository.get_active_for_jurisdiction_and_category(
                payload.jurisdiction,
                payload.category,
            )

            if existing_active is not None and payload.supersedes_id != existing_active.id:
                raise RegulatoryBasisReleaseAlreadyActive()

        content_hash = _compute_content_hash(
            [v.id for v in source_versions],
            [v.id for v in requirement_versions],
            [v.id for v in rule_versions],
            payload.configuration,
        )

        data = payload.model_dump(
            exclude_unset=True,
            exclude={
                "source_version_ids",
                "requirement_version_ids",
                "rule_version_ids",
                "status",
            },
        )

        release = RegulatoryBasisRelease(
            status=status,
            content_hash=content_hash,
            **data,
        )
        release.source_versions = source_versions
        release.requirement_versions = requirement_versions
        release.rule_versions = rule_versions

        try:
            self.repository.create(release)

            if existing_active is not None:
                existing_active.status = RegulatoryBasisReleaseStatus.SUPERSEDED.value
                existing_active.superseded_by_id = release.id
                existing_active.retired_at = datetime.now(timezone.utc)
                self.repository.update(existing_active)

            if status == RegulatoryBasisReleaseStatus.ACTIVE.value:
                self._publish_activated(
                    release,
                    previous_active_release_id=existing_active.id if existing_active else None,
                    actor_user_id=actor_user_id,
                    correlation_id=correlation_id,
                )

            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise RegulatoryBasisReleaseDuplicateContent()

        return release

    def update(
        self,
        release_id: UUID,
        payload: RegulatoryBasisReleaseUpdate,
        actor_user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> RegulatoryBasisRelease:
        release = self.get_by_id(release_id)
        from_status = release.status

        data = payload.model_dump(exclude_unset=True)

        for field, value in data.items():
            setattr(release, field, value)

        # A known, separately-logged gap (see CLAUDE.md "Known
        # limitations"): update() can set status=ACTIVE directly,
        # bypassing create()'s own active-conflict/supersession
        # enforcement entirely - not fixed here, but the audit trail
        # must still be honest about every path that CAN reach ACTIVE,
        # not just the one with real conflict checking. previous_active
        # is looked up read-only, for the event payload only - update()
        # still does not supersede/flip anything the way create() does.
        newly_activated = (
            from_status != RegulatoryBasisReleaseStatus.ACTIVE.value
            and release.status == RegulatoryBasisReleaseStatus.ACTIVE.value
        )
        if newly_activated:
            previous_active = self.repository.get_active_for_jurisdiction_and_category(
                release.jurisdiction, release.category,
            )
            self._publish_activated(
                release,
                previous_active_release_id=(
                    previous_active.id
                    if previous_active and previous_active.id != release.id
                    else None
                ),
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
            )

        self.repository.update(release)
        self.db.commit()

        return release
