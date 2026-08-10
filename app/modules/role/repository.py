from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Role


class RoleRepository(BaseRepository[Role]):
    """
    Repository for Role-specific database operations.
    """

    def __init__(self, db: Session):
        super().__init__(db, Role)

    def get_all(
    self,
    organization_id: UUID,
) -> list[Role]:

        statement = (
        select(Role)
        .where(
            Role.organization_id == organization_id,
            Role.is_active.is_(True),
        )
        .order_by(Role.created_at.desc())
    )

        return list(self.db.scalars(statement))

    def get_by_code(
        self,
        organization_id: UUID,
        code: str,
    ) -> Role | None:

        statement = (
            select(Role)
            .where(
                Role.organization_id == organization_id,
                Role.code == code,
            )
        )

        return self.db.scalar(statement)

    def get_by_name(
        self,
        organization_id: UUID,
        name: str,
    ) -> Role | None:

        statement = (
            select(Role)
            .where(
                Role.organization_id == organization_id,
                Role.name == name,
            )
        )

        return self.db.scalar(statement)
    def get_by_id(
    self,
    organization_id: UUID,
    role_id: UUID,
) -> Role | None:

        statement = (
        select(Role)
        .where(
            Role.id == role_id,
            Role.organization_id == organization_id,
        )
    )

        return self.db.scalar(statement)
        def exists(
    self,
    organization_id: UUID,
    code: str,
) -> bool:

            return (
        self.get_by_code(
            organization_id,
            code,
        )
        is not None
    )