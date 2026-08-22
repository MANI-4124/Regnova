from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import AssessmentRun, AssessmentRunStatus, DimensionAssessment, StepRun


class AssessmentRunRepository(BaseRepository[AssessmentRun]):
    """
    Repository for AssessmentRun. Organization-scoped, like
    ProductMarketState.
    """

    def __init__(self, db: Session):
        super().__init__(db, AssessmentRun)

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[AssessmentRun]:
        statement = (
            select(AssessmentRun)
            .where(
                AssessmentRun.organization_id == organization_id,
                AssessmentRun.product_market_state_id == product_market_state_id,
            )
            .order_by(AssessmentRun.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        run_id: UUID,
    ) -> AssessmentRun | None:
        statement = select(AssessmentRun).where(
            AssessmentRun.id == run_id,
            AssessmentRun.organization_id == organization_id,
            AssessmentRun.product_market_state_id == product_market_state_id,
        )

        return self.db.scalar(statement)


class StepRunRepository(BaseRepository[StepRun]):
    def __init__(self, db: Session):
        super().__init__(db, StepRun)

    def get_for_run_dimension(
        self,
        assessment_run_id: UUID,
        dimension: str,
    ) -> list[StepRun]:
        statement = select(StepRun).where(
            StepRun.assessment_run_id == assessment_run_id,
            StepRun.dimension == dimension,
        )

        return list(self.db.scalars(statement))

    def get_all_for_run(self, assessment_run_id: UUID) -> list[StepRun]:
        statement = select(StepRun).where(
            StepRun.assessment_run_id == assessment_run_id,
        )

        return list(self.db.scalars(statement))


class DimensionAssessmentRepository(BaseRepository[DimensionAssessment]):
    def __init__(self, db: Session):
        super().__init__(db, DimensionAssessment)

    def get_all_for_run(self, assessment_run_id: UUID) -> list[DimensionAssessment]:
        statement = select(DimensionAssessment).where(
            DimensionAssessment.assessment_run_id == assessment_run_id,
        )

        return list(self.db.scalars(statement))

    def get_latest_for_run_dimension(
        self,
        assessment_run_id: UUID,
        dimension: str,
    ) -> DimensionAssessment | None:
        """
        _run_dimension writes exactly one DimensionAssessment per
        (assessment_run, dimension) - this fetches it back right after
        MarketReadinessService triggers a fresh run for that dimension.
        """

        statement = (
            select(DimensionAssessment)
            .where(
                DimensionAssessment.assessment_run_id == assessment_run_id,
                DimensionAssessment.dimension == dimension,
            )
            .order_by(DimensionAssessment.created_at.desc())
            .limit(1)
        )

        return self.db.scalar(statement)

    def get_latest_reusable(
        self,
        product_market_state_id: UUID,
        dimension: str,
        product_version_id: UUID | None,
        regulatory_basis_release_id: UUID | None,
    ) -> DimensionAssessment | None:
        """
        Reuse-safety for Market Readiness (FR-05 "reusing valid current
        sub-assessments where safe"): the most recent DimensionAssessment
        for this (product_market_state, dimension), whose originating
        AssessmentRun pinned the exact same product_version_id and
        regulatory_basis_release_id being pinned now, and which didn't
        FAIL. Not input-fact hashing - AC-FR-05-01 names product version
        and regulatory basis release as what reproducibility pins on,
        and reuse's whole point is skipping re-submission of facts, so
        there'd be nothing to hash against anyway.
        """

        statement = (
            select(DimensionAssessment)
            .join(AssessmentRun, AssessmentRun.id == DimensionAssessment.assessment_run_id)
            .where(
                AssessmentRun.product_market_state_id == product_market_state_id,
                AssessmentRun.status != AssessmentRunStatus.FAILED.value,
                AssessmentRun.product_version_id == product_version_id,
                AssessmentRun.regulatory_basis_release_id == regulatory_basis_release_id,
                DimensionAssessment.dimension == dimension,
            )
            .order_by(DimensionAssessment.created_at.desc())
            .limit(1)
        )

        return self.db.scalar(statement)
