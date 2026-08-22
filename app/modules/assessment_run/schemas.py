from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AssessmentRunCreate(BaseModel):

    product_market_state_id: UUID

    # Kept generic (dimension-keyed) - see CLAUDE.md "Assessment engine".
    # input_facts["CLAIMS"] looks like {"product": {...}, "claims": [...]}.
    # input_facts["LABEL"] looks like {"product": {...}, "label_fields": [...]}.
    # input_facts["DOCUMENTS"] looks like {"product": {...},
    # "documents": [{"document_type": ..., "status": ..., <field>: {"value",
    # "confidence"}, ...}], "consistency_checks": [{"check_key": ...,
    # "outcome": {"value", "confidence"}, ...}]} - the documents[] checklist
    # itself is derived from the regulatory basis, not this list; entries
    # here are matched against it by document_type, and anything without a
    # matching checklist rule is ignored.
    dimensions: list[str]
    input_facts: dict[str, Any] = {}


class StepRunResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    dimension: str
    step_type: str
    rule_version_id: UUID | None
    subject_key: str | None
    input_facts: dict[str, Any]
    input_hash: str
    outcome: str | None
    trace: list[Any] | None
    status: str
    error_message: str | None


class DimensionAssessmentResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    dimension: str
    state: str


class AssessmentRunResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    product_market_state_id: UUID
    product_version_id: UUID
    regulatory_basis_release_id: UUID
    status: str
    requested_by_user_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime


class AssessmentRunDetailResponse(AssessmentRunResponse):

    step_runs: list[StepRunResponse]
    dimension_assessments: list[DimensionAssessmentResponse]
