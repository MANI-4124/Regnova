from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.auth.dependencies import get_current_active_user
from app.modules.user.models import User

from .service import RBACService


def require_admin(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:

    RBACService.require_role(
        db,
        current_user,
        "ADMIN",
    )

    return current_user


def require_manager(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:

    RBACService.require_role(
        db,
        current_user,
        "ADMIN",
        "MANAGER",
    )

    return current_user


def require_employee(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:

    RBACService.require_role(
        db,
        current_user,
        "ADMIN",
        "MANAGER",
        "EMPLOYEE",
    )

    return current_user