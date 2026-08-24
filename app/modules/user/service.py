from __future__ import annotations
from app.modules.auth.security import hash_password
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.repository import OutboxRepository

from .exceptions import (
    PermanentAdminProtected,
    UserAlreadyExists,
    UserNotFound,
)
from .models import User
from .repository import UserRepository
from .schemas import (
    UserCreate,
    UserResponse,
    UserUpdate,
)


class UserService:

    def __init__(
        self,
        db: Session,
    ):
        self.db = db
        self.repository = UserRepository(db)
        self.outbox = OutboxRepository(db)

    def get_all(
        self,
        organization_id: UUID,
    ) -> list[UserResponse]:

        users = self.repository.get_all(
            organization_id,
        )

        return [
            UserResponse.model_validate(user)
            for user in users
        ]

    def get_by_id(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> UserResponse:

        user = self.repository.get_by_id(
            organization_id,
            user_id,
        )

        if user is None:
            raise UserNotFound()

        return UserResponse.model_validate(user)

    def create(
        self,
        organization_id: UUID,
        payload: UserCreate,
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> UserResponse:

        if self.repository.get_by_email(
            organization_id,
            payload.email,
        ):
            raise UserAlreadyExists()

        user = User(
            organization_id=organization_id,
            role_id=payload.role_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            # Hash password before storing
password_hash=hash_password(payload.password),
            phone=payload.phone,
        )

        try:
            user = self.repository.create(user)

            self.outbox.append(
                organization_id=organization_id,
                event_type="MembershipChanged",
                schema_version=1,
                payload={
                    "user_id": str(user.id),
                    "organization_id": str(organization_id),
                    "role_id": str(user.role_id),
                    "change": "created",
                },
                correlation_id=correlation_id,
                actor_user_id=actor_user_id,
            )

            self.db.commit()

        except IntegrityError:
            self.db.rollback()
            raise UserAlreadyExists()

        self.repository.refresh(user)

        return UserResponse.model_validate(user)

    def update(
        self,
        organization_id: UUID,
        user_id: UUID,
        payload: UserUpdate,
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> UserResponse:

        user = self.repository.get_by_id(
            organization_id,
            user_id,
        )

        if user is None:
            raise UserNotFound()

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        # Structural, not a role check on the caller - refused
        # unconditionally, even for another ADMIN, even for the CEO's
        # own request. See User.is_permanent_admin.
        if user.is_permanent_admin and (
            ("role_id" in update_data and update_data["role_id"] != user.role_id)
            or update_data.get("is_active") is False
        ):
            raise PermanentAdminProtected()

        membership_changed = bool(
            {"role_id", "is_active"} & update_data.keys()
        )

        for field, value in update_data.items():
            setattr(user, field, value)

        if membership_changed:
            self.outbox.append(
                organization_id=organization_id,
                event_type="MembershipChanged",
                schema_version=1,
                payload={
                    "user_id": str(user.id),
                    "organization_id": str(organization_id),
                    "role_id": str(user.role_id),
                    "is_active": user.is_active,
                    "change": "updated",
                },
                correlation_id=correlation_id,
                actor_user_id=actor_user_id,
            )

        self.db.commit()

        self.repository.refresh(user)

        return UserResponse.model_validate(user)

    def delete(
        self,
        organization_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> None:

        user = self.repository.get_by_id(
            organization_id,
            user_id,
        )

        if user is None:
            raise UserNotFound()

        if user.is_permanent_admin:
            raise PermanentAdminProtected()

        self.outbox.append(
            organization_id=organization_id,
            event_type="MembershipChanged",
            schema_version=1,
            payload={
                "user_id": str(user.id),
                "organization_id": str(organization_id),
                "change": "revoked",
            },
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )

        self.repository.delete(user)

        self.db.commit()