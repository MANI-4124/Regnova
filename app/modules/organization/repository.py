from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Organization


class OrganizationRepository:
    """
    Handles all database operations for Organization.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> list[Organization]:
        statement = (
            select(Organization)
            .order_by(Organization.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
    ) -> Organization | None:

        return self.db.get(
            Organization,
            organization_id,
        )

    def create(
        self,
        organization: Organization,
    ) -> Organization:

        self.db.add(organization)
        self.db.flush()
        self.db.refresh(organization)

        return organization

    def update(
        self,
        organization: Organization,
    ) -> Organization:

        self.db.flush()
        self.db.refresh(organization)

        return organization

    def delete(
        self,
        organization: Organization,
    ) -> None:

        self.db.delete(organization)