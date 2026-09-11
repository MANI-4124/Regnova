from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session, get_query_classifier
from app.modules.rbac.dependencies import require_employee
from app.modules.user.models import User
from app.query_classification import QueryClassifier

from .exceptions import AskRegnovaQueryNotFound
from .repository import AskRegnovaQueryRepository
from .schemas import AskRegnovaAskRequest, AskRegnovaQueryResponse
from .service import AskRegnovaService

router = APIRouter(
    prefix="/ask",
    tags=["Ask RegNova"],
)


def get_ask_regnova_service(
    db: Session = Depends(get_db_session),
    classifier: QueryClassifier = Depends(get_query_classifier),
) -> AskRegnovaService:
    return AskRegnovaService(db, classifier)


@router.post(
    "",
    response_model=AskRegnovaQueryResponse,
)
def ask_regnova(
    payload: AskRegnovaAskRequest,
    current_user: User = Depends(require_employee),
    service: AskRegnovaService = Depends(get_ask_regnova_service),
):
    """
    require_employee is the ROUTER'S own gate - the lowest bar any
    shipped intent needs (REGULATORY_GRAPH's REQUIREMENT_DETAIL). Each
    handler re-checks a stricter tier itself when its own underlying
    data normally requires one (see CLAUDE.md "Ask RegNova" point 5) -
    a single flat gate here would let a low-tier user reach Finding/
    ProductMarketState data merely by phrasing a question about it.
    """
    return service.ask(
        current_user.organization_id,
        payload.question,
        current_user=current_user,
    )


@router.get(
    "",
    response_model=list[AskRegnovaQueryResponse],
)
def get_ask_regnova_history(
    current_user: User = Depends(require_employee),
    db: Session = Depends(get_db_session),
):
    return AskRegnovaQueryRepository(db).get_all(current_user.organization_id)


@router.get(
    "/{query_id}",
    response_model=AskRegnovaQueryResponse,
)
def get_ask_regnova_query(
    query_id: UUID,
    current_user: User = Depends(require_employee),
    db: Session = Depends(get_db_session),
):
    query = AskRegnovaQueryRepository(db).get_by_id(current_user.organization_id, query_id)
    if query is None:
        raise AskRegnovaQueryNotFound()
    return query
