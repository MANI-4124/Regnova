from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.rbac.dependencies import (
    require_admin,
    require_employee,
)
from app.modules.user.models import User

from .schemas import (
    RuleCreate,
    RuleResponse,
    RuleUpdate,
)
from .service import RuleService

router = APIRouter(
    prefix="/rules",
    tags=["Rules"],
)


def get_rule_service(
    db: Session = Depends(get_db_session),
) -> RuleService:
    return RuleService(db)


@router.get(
    "",
    response_model=list[RuleResponse],
)
def get_rules(
    current_user: User = Depends(require_employee),
    service: RuleService = Depends(get_rule_service),
):
    return service.get_all()


@router.get(
    "/{rule_id}",
    response_model=RuleResponse,
)
def get_rule(
    rule_id: UUID,
    current_user: User = Depends(require_employee),
    service: RuleService = Depends(get_rule_service),
):
    return service.get_by_id(rule_id)


@router.post(
    "",
    response_model=RuleResponse,
)
def create_rule(
    payload: RuleCreate,
    # NOTE: require_admin here is an interim placeholder, not a real
    # authorization decision - same unresolved actor-model gap as
    # Source/Requirement. See CLAUDE.md "Regulatory content ownership".
    current_user: User = Depends(require_admin),
    service: RuleService = Depends(get_rule_service),
):
    return service.create(payload)


@router.put(
    "/{rule_id}",
    response_model=RuleResponse,
)
def update_rule(
    rule_id: UUID,
    payload: RuleUpdate,
    current_user: User = Depends(require_admin),  # interim placeholder - see CLAUDE.md
    service: RuleService = Depends(get_rule_service),
):
    return service.update(rule_id, payload)
