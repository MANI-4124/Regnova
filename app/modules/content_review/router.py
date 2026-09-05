from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import require_regulatory_content_writer
from app.modules.user.models import User

from .schemas import BulkContentReviewRequest, BulkContentReviewResponse
from .service import BulkContentReviewService

router = APIRouter(
    prefix="/content-review",
    tags=["Content Review"],
)


def get_bulk_content_review_service(
    db: Session = Depends(get_db_session),
) -> BulkContentReviewService:
    return BulkContentReviewService(db)


@router.post(
    "/bulk-verify",
    response_model=BulkContentReviewResponse,
)
def bulk_verify_content(
    payload: BulkContentReviewRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: BulkContentReviewService = Depends(get_bulk_content_review_service),
):
    results = service.bulk_verify(
        payload.items, actor_user_id=current_user.id, rationale=payload.rationale,
    )
    return BulkContentReviewResponse(results=results)


@router.post(
    "/bulk-activate",
    response_model=BulkContentReviewResponse,
)
def bulk_activate_content(
    payload: BulkContentReviewRequest,
    current_user: User = Depends(require_regulatory_content_writer),
    service: BulkContentReviewService = Depends(get_bulk_content_review_service),
):
    results = service.bulk_activate(
        payload.items, actor_user_id=current_user.id, rationale=payload.rationale,
    )
    return BulkContentReviewResponse(results=results)
