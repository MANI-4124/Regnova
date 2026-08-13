from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .exceptions import InvalidRequirementResultOutcome
from .models import (
    APPLICABILITY_OUTCOMES,
    SATISFACTION_OUTCOMES,
    RequirementResult,
)


class RequirementResultRepository(BaseRepository[RequirementResult]):
    """
    Repository for RequirementResult - no public router (system-produced
    lineage data, same "no router.py" shape as audit's OutboxEvent).
    """

    def __init__(self, db: Session):
        super().__init__(db, RequirementResult)

    def create_validated(
        self,
        *,
        step_run_id: UUID,
        assessment_run_id: UUID,
        requirement_version_id: UUID,
        rule_version_id: UUID | None,
        output_type: str,
        outcome: str,
        predicate_inputs: dict[str, Any],
        source_locations: list | None = None,
    ) -> RequirementResult:
        """
        Validates outcome against the closed vocabulary for output_type
        before creating the row. Does not commit - the caller (
        AssessmentRunService) commits alongside the rest of the step.
        """

        allowed = (
            APPLICABILITY_OUTCOMES if output_type == "APPLICABILITY" else SATISFACTION_OUTCOMES
        )

        if outcome not in allowed:
            raise InvalidRequirementResultOutcome(outcome, allowed)

        result = RequirementResult(
            step_run_id=step_run_id,
            assessment_run_id=assessment_run_id,
            requirement_version_id=requirement_version_id,
            rule_version_id=rule_version_id,
            outcome=outcome,
            predicate_inputs=predicate_inputs,
        )

        if source_locations:
            result.source_locations = source_locations

        self.db.add(result)
        self.db.flush()
        self.db.refresh(result)

        return result

    def get_for_run_dimension(
        self,
        assessment_run_id: UUID,
        dimension: str,
    ) -> list[RequirementResult]:
        # dimension is on StepRun, not RequirementResult itself - join
        # through step_run_id to filter by it.
        from app.modules.assessment_run.models import StepRun

        statement = (
            select(RequirementResult)
            .join(StepRun, StepRun.id == RequirementResult.step_run_id)
            .where(
                RequirementResult.assessment_run_id == assessment_run_id,
                StepRun.dimension == dimension,
            )
        )

        return list(self.db.scalars(statement))
