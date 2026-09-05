from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.auth.dependencies import get_current_active_user
from app.modules.user.models import User

from .schemas import NotificationResponse, UnreadCountResponse
from .service import NotificationService

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


def get_notification_service(
    db: Session = Depends(get_db_session),
) -> NotificationService:
    return NotificationService(db)


@router.get(
    "",
    response_model=list[NotificationResponse],
)
def get_notifications(
    unread_only: bool = False,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
):
    """
    Always scoped to the caller's own notifications - there is no
    organization_id here to check, and none to leak: recipient_user_id
    is the only scoping this resource has, see models.py.
    """
    return service.get_all(current_user.id, unread_only=unread_only)


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
)
def get_unread_notification_count(
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
):
    return UnreadCountResponse(unread_count=service.get_unread_count(current_user.id))


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
)
def mark_notification_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_active_user),
    service: NotificationService = Depends(get_notification_service),
):
    return service.mark_read(current_user.id, notification_id)
