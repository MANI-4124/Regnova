from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_correlation_id, get_db_session
from app.modules.rbac.dependencies import require_manager
from app.modules.user.models import User

from .schemas import EvidenceCreate, EvidenceResponse
from .service import EvidenceService

router = APIRouter(
    prefix="/evidence",
    tags=["Evidence"],
)


def get_evidence_service(
    db: Session = Depends(get_db_session),
) -> EvidenceService:
    return EvidenceService(db)


@router.get(
    "",
    response_model=list[EvidenceResponse],
)
def get_evidence(
    product_id: UUID | None = None,
    current_user: User = Depends(require_manager),
    service: EvidenceService = Depends(get_evidence_service),
):
    return service.get_all(current_user.organization_id, product_id)


@router.get(
    "/{evidence_id}",
    response_model=EvidenceResponse,
)
def get_evidence_by_id(
    evidence_id: UUID,
    current_user: User = Depends(require_manager),
    service: EvidenceService = Depends(get_evidence_service),
):
    return service.get_by_id(current_user.organization_id, evidence_id)


@router.post(
    "",
    response_model=EvidenceResponse,
)
def create_evidence(
    payload: EvidenceCreate,
    current_user: User = Depends(require_manager),
    correlation_id: str = Depends(get_correlation_id),
    service: EvidenceService = Depends(get_evidence_service),
):
    return service.create(
        current_user.organization_id,
        payload,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )


@router.delete(
    "/{evidence_id}",
)
def delete_evidence(
    evidence_id: UUID,
    current_user: User = Depends(require_manager),
    correlation_id: str = Depends(get_correlation_id),
    service: EvidenceService = Depends(get_evidence_service),
):
    service.delete(
        current_user.organization_id,
        evidence_id,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )

    return {
        "message": "Evidence deleted successfully."
    }
