from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import FindingNotFound
from .models import Finding, FindingRevision, FindingStatus
from .repository import FindingRepository, FindingRevisionRepository


class FindingService:
    """
    Finding/FindingRevision service. propose() is the engine's entry
    point (called from AssessmentRunService) - not exposed on the
    router, which is read-only in this pass (no RA-review workflow
    exists yet to drive status transitions).
    """

    def __init__(self, db: Session):
        self.db = db
        self.findings = FindingRepository(db)
        self.revisions = FindingRevisionRepository(db)

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[Finding]:
        return self.findings.get_all(organization_id, product_market_state_id)

    def get_by_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
    ) -> Finding:
        finding = self.findings.get_by_id(
            organization_id,
            product_market_state_id,
            finding_id,
        )

        if finding is None:
            raise FindingNotFound()

        return finding

    def get_revisions(self, finding_id: UUID) -> list[FindingRevision]:
        return self.revisions.get_all(finding_id)

    def propose(
        self,
        *,
        organization_id: UUID,
        product_market_state_id: UUID,
        dimension: str,
        assessment_run_id: UUID,
        requirement_version_id: UUID | None,
        rule_version_id: UUID | None,
        subject_key: str | None,
        issue_type: str,
        observed_value: str,
        severity: str,
        hard_gate_effect: bool,
        rationale: str,
        normalized_value: str | None = None,
        observed_location: dict[str, Any] | None = None,
    ) -> Finding | None:
        """
        Idempotent re-proposal: the same (product_market_state,
        dimension, requirement_version, subject_key) tuple reuses its
        existing Finding rather than spawning a duplicate on every
        re-run. If a human has already acted on it (status moved past
        PROPOSED), a fresh automated detection defers to that - no new
        revision is written, and this returns None. If it's still
        PROPOSED (never reviewed), a fresh revision is appended so the
        latest evidence is current.
        """

        existing = self.findings.find_open_match(
            product_market_state_id,
            dimension,
            requirement_version_id,
            subject_key,
        )

        if existing is not None:
            latest = self.revisions.get_latest(existing.id)
            if latest is not None and latest.status != FindingStatus.PROPOSED.value:
                return None

            next_revision_number = (latest.revision_number + 1) if latest else 1
            finding = existing
        else:
            finding = Finding(
                organization_id=organization_id,
                product_market_state_id=product_market_state_id,
                dimension=dimension,
                requirement_version_id=requirement_version_id,
                rule_version_id=rule_version_id,
                subject_key=subject_key,
            )
            self.findings.create(finding)
            next_revision_number = 1

        revision = FindingRevision(
            finding_id=finding.id,
            revision_number=next_revision_number,
            assessment_run_id=assessment_run_id,
            issue_type=issue_type,
            observed_value=observed_value,
            normalized_value=normalized_value,
            observed_location=observed_location,
            severity=severity,
            status=FindingStatus.PROPOSED.value,
            hard_gate_effect=hard_gate_effect,
            rationale=rationale,
        )
        self.revisions.create(revision)

        return finding
