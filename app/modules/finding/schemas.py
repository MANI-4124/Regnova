from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FindingRevisionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    finding_id: UUID
    revision_number: int

    assessment_run_id: UUID | None

    issue_type: str
    observed_value: str
    normalized_value: str | None
    observed_location: dict[str, Any] | None

    severity: str
    status: str
    disposition: str | None
    hard_gate_effect: bool
    rationale: str

    action_type: str | None
    suggested_value: str | None
    resolution_criteria: str | None
    owner_user_id: UUID | None
    due_date: datetime | None

    resolution_decision: str | None
    resolved_at: datetime | None
    superseding_finding_id: UUID | None

    source_location_ids: list[UUID]

    created_at: datetime


class FindingResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    product_market_state_id: UUID
    dimension: str

    requirement_version_id: UUID | None
    rule_version_id: UUID | None
    subject_key: str | None
    human_reference: str | None

    created_at: datetime


class FindingDetailResponse(FindingResponse):

    revisions: list[FindingRevisionResponse]
