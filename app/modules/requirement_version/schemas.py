from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RequirementVersionCreate(BaseModel):

    jurisdiction: str
    market: str
    authority: str
    category: str
    subcategory: str | None = None
    pathway: str | None = None
    dimension: str
    context: dict[str, Any] | None = None
    context_schema_name: str | None = None
    context_schema_version: int | None = None

    applicability_predicate: dict[str, Any] | None = None
    applicability_predicate_schema_name: str | None = None
    applicability_predicate_schema_version: int | None = None
    applicability_required_inputs: list[Any] | None = None
    unknown_behavior: str | None = None

    obligation_type: str
    canonical_statement: str
    customer_safe_explanation: str | None = None

    accepted_evidence_types: list[Any] | None = None
    field_checks: dict[str, Any] | None = None
    validity_scope_rules: dict[str, Any] | None = None
    verification_level: str | None = None

    default_severity: str
    is_hard_gate: bool | None = None
    importance_weight: float | None = None
    approval_policy: str | None = None

    authority_interpretation_label: str

    effective_from: datetime | None = None
    effective_to: datetime | None = None

    source_location_ids: list[UUID] | None = None

    notes: str | None = None


class RequirementVersionUpdate(BaseModel):

    jurisdiction: str | None = None
    market: str | None = None
    authority: str | None = None
    category: str | None = None
    subcategory: str | None = None
    pathway: str | None = None
    dimension: str | None = None
    context: dict[str, Any] | None = None
    context_schema_name: str | None = None
    context_schema_version: int | None = None

    applicability_predicate: dict[str, Any] | None = None
    applicability_predicate_schema_name: str | None = None
    applicability_predicate_schema_version: int | None = None
    applicability_required_inputs: list[Any] | None = None
    unknown_behavior: str | None = None

    obligation_type: str | None = None
    canonical_statement: str | None = None
    customer_safe_explanation: str | None = None

    accepted_evidence_types: list[Any] | None = None
    field_checks: dict[str, Any] | None = None
    validity_scope_rules: dict[str, Any] | None = None
    verification_level: str | None = None

    default_severity: str | None = None
    is_hard_gate: bool | None = None
    importance_weight: float | None = None
    approval_policy: str | None = None

    author_user_id: UUID | None = None
    reviewer_user_id: UUID | None = None
    verified_at: datetime | None = None
    authority_interpretation_label: str | None = None

    effective_from: datetime | None = None
    effective_to: datetime | None = None
    recorded_at: datetime | None = None
    retired_at: datetime | None = None
    supersedes_id: UUID | None = None
    superseded_by_id: UUID | None = None

    status: str | None = None

    source_location_ids: list[UUID] | None = None

    notes: str | None = None


class RequirementVersionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    requirement_id: UUID
    status: str

    jurisdiction: str
    market: str
    authority: str
    category: str
    subcategory: str | None
    pathway: str | None
    dimension: str
    context: dict[str, Any] | None
    context_schema_name: str | None
    context_schema_version: int | None

    applicability_predicate: dict[str, Any] | None
    applicability_predicate_schema_name: str | None
    applicability_predicate_schema_version: int | None
    applicability_required_inputs: list[Any] | None
    unknown_behavior: str

    obligation_type: str
    canonical_statement: str
    customer_safe_explanation: str | None

    accepted_evidence_types: list[Any] | None
    field_checks: dict[str, Any] | None
    validity_scope_rules: dict[str, Any] | None
    verification_level: str | None

    default_severity: str
    is_hard_gate: bool
    importance_weight: float | None
    approval_policy: str | None

    author_user_id: UUID | None
    reviewer_user_id: UUID | None
    verified_at: datetime | None
    authority_interpretation_label: str

    effective_from: datetime | None
    effective_to: datetime | None
    recorded_at: datetime | None
    retired_at: datetime | None
    supersedes_id: UUID | None
    superseded_by_id: UUID | None

    source_location_ids: list[UUID]

    notes: str | None
