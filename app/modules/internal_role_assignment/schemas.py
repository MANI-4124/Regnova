from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InternalRoleAssignmentPropose(BaseModel):

    user_id: UUID
    role_code: str
    scope: list[Any] | None = None
    rationale: str


class InternalRoleAssignmentDecide(BaseModel):

    approve: bool
    decision_rationale: str | None = None


class InternalRoleAssignmentProposeRevocation(BaseModel):

    rationale: str


class InternalRoleAssignmentDecideRevocation(BaseModel):

    approve: bool
    decision_rationale: str | None = None


class InternalRoleAssignmentRevoke(BaseModel):

    reason: str


class InternalRoleAssignmentResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    user_id: UUID
    role_code: str
    scope: list[Any] | None
    status: str

    proposed_by_user_id: UUID | None
    proposed_at: datetime
    rationale: str

    approver_user_id: UUID | None
    decided_at: datetime | None
    decision_rationale: str | None
    content_hash: str

    revocation_proposed_by_user_id: UUID | None
    revocation_proposed_at: datetime | None
    revocation_rationale: str | None

    revoked_by_user_id: UUID | None
    revoked_at: datetime | None
    revocation_reason: str | None

    expires_at: datetime | None
    superseded_by_id: UUID | None

    created_at: datetime
