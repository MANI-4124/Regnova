from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Organization


class OrganizationRepository(BaseRepository[Organization]):
    """
    Repository for Organization-specific database operations.
    """

    def __init__(self, db: Session):
        super().__init__(db, Organization)

    def get_all(self) -> list[Organization]:
        """
        Return all organizations ordered by newest first.
        """
        statement = (
            select(Organization)
            .order_by(Organization.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_name(
        self,
        name: str,
    ) -> Organization | None:
        """
        Return an organization by its unique name.
        """
        statement = (
            select(Organization)
            .where(Organization.name == name)
        )

        return self.db.scalar(statement)

    def get_internal(self) -> Organization | None:
        """
        The single "tenant zero" organization (is_internal=True), if one
        has been provisioned - used by internal_role_assignment to
        validate that both the target of a grant and the person
        proposing it are RegNova staff, not a customer-org account.
        """

        statement = select(Organization).where(Organization.is_internal.is_(True))

        return self.db.scalar(statement)