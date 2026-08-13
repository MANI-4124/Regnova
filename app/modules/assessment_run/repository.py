from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import AssessmentRun, DimensionAssessment, StepRun


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
