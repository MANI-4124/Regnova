from sqlalchemy.orm import Session

from app.modules.role.repository import RoleRepository
from app.modules.user.models import User

from .exceptions import PermissionDenied


class RBACService:
    """
    Permission checker.
    """

    @staticmethod
    def require_role(
        db: Session,
        user: User,
        *roles: str,
    ) -> None:

        role = RoleRepository(db).get_by_id(
            user.organization_id,
            user.role_id,
        )

        if role is None:
            raise PermissionDenied()

        if role.code.upper() not in roles:
            raise PermissionDenied()