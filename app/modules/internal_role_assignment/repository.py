from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import InternalRoleAssignment, InternalRoleAssignmentStatus


class InternalRoleAssignmentRepository(BaseRepository[InternalRoleAssignment]):
    """
    Repository for InternalRoleAssignment - not organization-scoped
    (every row inherently concerns tenant-zero users only, enforced at
    the service layer, not by a scoping FK on this table).
    """

    def __init__(self, db: Session):
        super().__init__(db, InternalRoleAssignment)

    def get_all(self) -> list[InternalRoleAssignment]:
        statement = select(InternalRoleAssignment).order_by(
            InternalRoleAssignment.created_at.desc(),
        )

        return list(self.db.scalars(statement))

    def get_active_for_user_role(
        self,
        user_id: UUID,
        role_code: str,
    ) -> InternalRoleAssignment | None:
        """
        The single currently-in-force assignment for (user, role_code) -
        the permission-check query every require_* internal-role
        dependency uses, and the lookup _supersede_prior_approved uses
        to find what a fresh approval replaces.
        """

        statement = (
            select(InternalRoleAssignment)
            .where(
                InternalRoleAssignment.user_id == user_id,
                InternalRoleAssignment.role_code == role_code,
                InternalRoleAssignment.status == InternalRoleAssignmentStatus.APPROVED.value,
            )
            .order_by(InternalRoleAssignment.created_at.desc())
            .limit(1)
        )

        return self.db.scalar(statement)
