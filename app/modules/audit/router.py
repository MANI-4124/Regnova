from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_correlation_id, get_db_session
from app.modules.auth.dependencies import get_current_active_user
from app.modules.rbac.dependencies import require_manager
from app.modules.user.models import User

from .schemas import AuditEventInternalResponse, AuditEventResponse
from .service import AuditService

router = APIRouter(
    prefix="/audit-events",
    tags=["Audit"],
)


def get_audit_service(
    db: Session = Depends(get_db_session),
) -> AuditService:
    return AuditService(db)


@router.get(
    "",
    response_model=list[AuditEventResponse],
)
def get_audit_events(
    product_id: UUID | None = None,
    product_market_state_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    event_type: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    current_user: User = Depends(require_manager),
    service: AuditService = Depends(get_audit_service),
):
    """
    The zero-exception path - organization_id is always
    current_user.organization_id, never client-supplied, exactly like
    every other org-scoped read in this codebase. Customer-visible tier
    only.
    """
    return service.get_customer_visible(
        current_user.organization_id,
        product_id=product_id,
        product_market_state_id=product_market_state_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )


@router.get(
    "/internal",
    response_model=list[AuditEventInternalResponse],
)
def get_internal_audit_events(
    organization_id: UUID,
    product_id: UUID | None = None,
    product_market_state_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    event_type: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    current_user: User = Depends(get_current_active_user),
    correlation_id: str = Depends(get_correlation_id),
    service: AuditService = Depends(get_audit_service),
):
    """
    The deliberate, narrow exception to "organization_id is always
    derived from the caller" - see CLAUDE.md "Audit log" for the full
    reasoning and why this is not precedent for the still-unbuilt RA
    Workbench. Authorization is NOT a router-level require_* dependency
    here (deliberately, same reasoning as FindingService's own
    transitions): which tiers this caller is cleared for depends on
    which specific internal roles they hold, computed in
    AuditService._resolve_internal_tier_grants, not a single role tier a
    static dependency could express. Bare authentication is the router-
    level floor; the service raises AuditReaderNotAuthorized (403) for
    anyone holding none of the qualifying roles. Every call - regardless
    of whether it returns any rows - is itself durably logged.
    """
    return service.get_internal(
        caller_user_id=current_user.id,
        organization_id=organization_id,
        correlation_id=correlation_id,
        product_id=product_id,
        product_market_state_id=product_market_state_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
