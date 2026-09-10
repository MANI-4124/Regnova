from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analysis import SemanticAnalyzer
from app.core.dependencies import get_correlation_id, get_db_session, get_semantic_analyzer
from app.modules.rbac.dependencies import require_admin, require_manager
from app.modules.user.models import User

from .schemas import (
    AssessmentRunCreate,
    AssessmentRunDetailResponse,
    AssessmentRunResponse,
    DimensionAssessmentResponse,
    StepRunResponse,
)
from .service import AssessmentRunService

router = APIRouter(
    prefix="/assessment-runs",
    tags=["Assessment Runs"],
)


def get_assessment_run_service(
    db: Session = Depends(get_db_session),
    semantic_analyzer: SemanticAnalyzer = Depends(get_semantic_analyzer),
) -> AssessmentRunService:
    return AssessmentRunService(db, semantic_analyzer=semantic_analyzer)


@router.get(
    "",
    response_model=list[AssessmentRunResponse],
)
def get_assessment_runs(
    product_market_state_id: UUID,
    current_user: User = Depends(require_manager),
    service: AssessmentRunService = Depends(get_assessment_run_service),
):
    return service.get_all(current_user.organization_id, product_market_state_id)


@router.get(
    "/{run_id}",
    response_model=AssessmentRunDetailResponse,
)
def get_assessment_run(
    run_id: UUID,
    product_market_state_id: UUID,
    current_user: User = Depends(require_manager),
    service: AssessmentRunService = Depends(get_assessment_run_service),
):
    run = service.get_by_id(current_user.organization_id, product_market_state_id, run_id)

    return AssessmentRunDetailResponse(
        **AssessmentRunResponse.model_validate(run).model_dump(),
        step_runs=[StepRunResponse.model_validate(s) for s in run.step_runs],
        dimension_assessments=[
            DimensionAssessmentResponse.model_validate(d) for d in run.dimension_assessments
        ],
    )


@router.post(
    "",
    response_model=AssessmentRunResponse,
)
def create_assessment_run(
    payload: AssessmentRunCreate,
    current_user: User = Depends(require_admin),
    correlation_id: str = Depends(get_correlation_id),
    service: AssessmentRunService = Depends(get_assessment_run_service),
):
    return service.create_and_run(
        current_user.organization_id,
        payload.product_market_state_id,
        payload,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )
