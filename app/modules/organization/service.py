from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.repository import AuditEventRepository, OutboxRepository

from .exceptions import (
    OrganizationAlreadyExists,
    OrganizationHasAuditHistory,
    OrganizationNotFound,
)
from .models import Organization
from .repository import OrganizationRepository
from .schemas import (
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)


def require_organization_synthetic(db: Session, organization_id: UUID) -> bool:
    """
    True only if Organization.is_synthetic is set - the actual,
    structural gate the free-tier Gemini training-data warnings across
    app/analysis/, app/extraction/, and app/query_classification/ named
    as "the real fix, logged not built" since the first AI slice. Fails
    closed (False = not eligible for a real external call) if the
    organization can't be found at all - should never happen for an
    authenticated request, but a lookup failure must never accidentally
    read as "eligible". Called from each AI-hop call site (the semantic
    peer hop, document extraction, Ask RegNova's classifier) immediately
    before invoking a real ("gemini") backend - never for the stub/noop
    backends, which make no external call regardless and stay exactly as
    invisible as they were before this flag existed. See CLAUDE.md
    "Ask RegNova".
    """
    organization = OrganizationRepository(db).get_by_id(organization_id)
    return organization is not None and organization.is_synthetic


class OrganizationService:
    """
    Business logic for Organization.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repository = OrganizationRepository(db)
        self.outbox = OutboxRepository(db)
        self.audit_events = AuditEventRepository(db)

    def get_all(self) -> list[OrganizationResponse]:
        organizations = self.repository.get_all()

        return [
            OrganizationResponse.model_validate(org)
            for org in organizations
        ]

    def get_by_id(
        self,
        organization_id: UUID,
    ) -> OrganizationResponse:

        organization = self.repository.get_by_id(organization_id)

        if organization is None:
            raise OrganizationNotFound()

        return OrganizationResponse.model_validate(organization)

    def create(
        self,
        payload: OrganizationCreate,
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> OrganizationResponse:

        organization = Organization(
            name=payload.name,
            industry=payload.industry,
            country=payload.country,
        )

        try:
            organization = self.repository.create(organization)

            self.outbox.append(
                organization_id=organization.id,
                event_type="WorkspaceActivated",
                schema_version=1,
                payload={
                    "organization_id": str(organization.id),
                    "name": organization.name,
                },
                correlation_id=correlation_id,
                actor_user_id=actor_user_id,
            )

            self.db.commit()

        except IntegrityError:
            self.db.rollback()
            raise OrganizationAlreadyExists()

        self.repository.refresh(organization)

        return OrganizationResponse.model_validate(organization)

    def update(
        self,
        organization_id: UUID,
        payload: OrganizationUpdate,
    ) -> OrganizationResponse:

        organization = self.repository.get_by_id(organization_id)

        if organization is None:
            raise OrganizationNotFound()

        update_data = payload.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(organization, field, value)

        try:
            self.db.commit()

        except IntegrityError:
            self.db.rollback()
            raise OrganizationAlreadyExists()

        self.repository.refresh(organization)

        return OrganizationResponse.model_validate(organization)

    def delete(
        self,
        organization_id: UUID,
    ) -> None:

        organization = self.repository.get_by_id(organization_id)

        if organization is None:
            raise OrganizationNotFound()

        # Enforced here AND at the DB level (AuditEvent.organization_id
        # is ondelete=RESTRICT) - SQLite in this test suite doesn't
        # enforce foreign keys at all, so this pre-check is what makes
        # the behavior real and verified here, not just documented
        # intent for Postgres. See OrganizationHasAuditHistory.
        if self.audit_events.exists_for_organization(organization_id):
            raise OrganizationHasAuditHistory()

        try:
            self.repository.delete(organization)
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise