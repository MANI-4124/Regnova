from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Finding, FindingRevision, FindingStatus


class FindingRepository(BaseRepository[Finding]):
    """
    Repository for Finding. Organization-scoped, like ProductMarketState
    (customer-visible issue data), not like the regulatory-content
    family.
    """

    def __init__(self, db: Session):
        super().__init__(db, Finding)

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[Finding]:
        statement = (
            select(Finding)
            .where(
                Finding.organization_id == organization_id,
                Finding.product_market_state_id == product_market_state_id,
            )
            .order_by(Finding.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_all_for_dimension(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        dimension: str,
    ) -> list[Finding]:
        """
        Same scoping as get_all, narrowed to one dimension - direct on
        Finding.dimension, not a join through RequirementVersion.
        RequirementVersion.dimension would miss any Finding whose
        requirement_version_id is null (C6's CALCULATION_COMPONENT
        rules are requirement-version-less), and Finding.dimension is
        already set directly at propose() time regardless. Used by
        FindingService.has_open_finding, which AssessmentRunService
        calls to check for a still-open Finding a fresh run's own rules
        didn't touch this time - see CLAUDE.md "Assessment engine".
        """
        statement = (
            select(Finding)
            .where(
                Finding.organization_id == organization_id,
                Finding.product_market_state_id == product_market_state_id,
                Finding.dimension == dimension,
            )
            .order_by(Finding.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        finding_id: UUID,
    ) -> Finding | None:
        statement = select(Finding).where(
            Finding.id == finding_id,
            Finding.organization_id == organization_id,
            Finding.product_market_state_id == product_market_state_id,
        )

        return self.db.scalar(statement)

    def find_open_match(
        self,
        product_market_state_id: UUID,
        dimension: str,
        requirement_version_id: UUID | None,
        subject_key: str | None,
    ) -> Finding | None:
        """
        Identity lookup for propose()'s idempotent reuse: the same claim
        x requirement issue, not yet superseded/rejected, gets a new
        FindingRevision instead of spawning a duplicate Finding on every
        re-run.
        """

        statement = (
            select(Finding)
            .join(FindingRevision, FindingRevision.finding_id == Finding.id)
            .where(
                Finding.product_market_state_id == product_market_state_id,
                Finding.dimension == dimension,
                Finding.requirement_version_id == requirement_version_id,
                Finding.subject_key == subject_key,
            )
            .order_by(Finding.created_at.desc())
        )

        for finding in self.db.scalars(statement).unique():
            latest = self.db.scalar(
                select(FindingRevision)
                .where(FindingRevision.finding_id == finding.id)
                .order_by(FindingRevision.revision_number.desc())
                .limit(1),
            )
            if latest and latest.status not in (
                FindingStatus.SUPERSEDED.value,
                FindingStatus.REJECTED.value,
            ):
                return finding

        return None


class FindingRevisionRepository(BaseRepository[FindingRevision]):
    def __init__(self, db: Session):
        super().__init__(db, FindingRevision)

    def get_all(self, finding_id: UUID) -> list[FindingRevision]:
        statement = (
            select(FindingRevision)
            .where(FindingRevision.finding_id == finding_id)
            .order_by(FindingRevision.revision_number.asc())
        )

        return list(self.db.scalars(statement))

    def get_latest(self, finding_id: UUID) -> FindingRevision | None:
        statement = (
            select(FindingRevision)
            .where(FindingRevision.finding_id == finding_id)
            .order_by(FindingRevision.revision_number.desc())
            .limit(1)
        )

        return self.db.scalar(statement)

    def get_latest_as_of(self, finding_id: UUID, as_of: datetime) -> FindingRevision | None:
        """
        The revision that was current at a specific point in time - not
        "whatever's current now". Findings keep accruing revisions
        after the StateSnapshot that used them was built (the review
        workflow happens later), so a bare finding_id reference drifts;
        this is the one genuinely new query AC-FR-14-01 reconstruction
        needs (see CLAUDE.md "Exports") - every other entity an export
        touches is already immutable-by-reference. Returns None if the
        Finding didn't exist yet as of `as_of` (its first revision is
        later than the requested point in time).
        """
        statement = (
            select(FindingRevision)
            .where(
                FindingRevision.finding_id == finding_id,
                FindingRevision.created_at <= as_of,
            )
            .order_by(FindingRevision.revision_number.desc())
            .limit(1)
        )

        return self.db.scalar(statement)

    def count_proposed_for_run_dimension(
        self,
        assessment_run_id: UUID,
        dimension: str,
    ) -> int:
        statement = (
            select(FindingRevision)
            .join(Finding, Finding.id == FindingRevision.finding_id)
            .where(
                FindingRevision.assessment_run_id == assessment_run_id,
                Finding.dimension == dimension,
            )
        )

        return len(list(self.db.scalars(statement)))
