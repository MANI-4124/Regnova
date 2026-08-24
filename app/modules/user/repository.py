from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import User


class UserRepository(BaseRepository[User]):
    """
    Repository for User database operations.
    """

    def __init__(self, db: Session):
        super().__init__(db, User)

    def get_all(
        self,
        organization_id: UUID,
    ) -> list[User]:

        statement = (
            select(User)
            .where(
                User.organization_id == organization_id,
                User.is_active.is_(True),
            )
            .order_by(
                User.created_at.desc(),
            )
        )

        return list(self.db.scalars(statement))

    def get_by_id(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> User | None:

        statement = (
            select(User)
            .where(
                User.id == user_id,
                User.organization_id == organization_id,
            )
        )

        return self.db.scalar(statement)

    def get_by_id_only(
        self,
        user_id: UUID,
    ) -> User | None:
        """
        Unscoped lookup by id alone - used by internal_role_assignment,
        which validates a target/proposer user against tenant-zero
        membership rather than the caller's own organization_id.
        """

        return super().get_by_id(user_id)

    def get_by_email(
        self,
        organization_id: UUID,
        email: str,
    ) -> User | None:

        statement = (
            select(User)
            .where(
                User.organization_id == organization_id,
                User.email == email,
            )
        )

        return self.db.scalar(statement)

    def get_by_email_global(
        self,
        email: str,
    ) -> User | None:

        statement = (
            select(User)
            .where(
                User.email == email,
            )
        )

        return self.db.scalar(statement)

    def update_last_login(
        self,
        user: User,
    ) -> None:

        self.db.flush()
        self.db.refresh(user)