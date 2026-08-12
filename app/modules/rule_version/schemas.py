from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RuleVersionCreate(BaseModel):

    requirement_version_id: UUID | None = None

    inputs: list[Any] | None = None
    inputs_schema_name: str | None = None
    inputs_schema_version: int | None = None

    condition: dict[str, Any]
    condition_schema_name: str | None = None
    condition_schema_version: int | None = None

    unknown_behavior: str | None = None

    output_type: str

    approval_policy: str | None = None

    effective_from: datetime | None = None
    effective_to: datetime | None = None

    test_fixtures: list[Any] | None = None
    test_fixtures_schema_name: str | None = None
    test_fixtures_schema_version: int | None = None

    source_location_ids: list[UUID] | None = None

    notes: str | None = None


class RuleVersionUpdate(BaseModel):

    requirement_version_id: UUID | None = None

    inputs: list[Any] | None = None
    inputs_schema_name: str | None = None
    inputs_schema_version: int | None = None

    condition: dict[str, Any] | None = None
    condition_schema_name: str | None = None
    condition_schema_version: int | None = None

    unknown_behavior: str | None = None

    output_type: str | None = None

    author_user_id: UUID | None = None
    reviewer_user_id: UUID | None = None
    verified_at: datetime | None = None
    approval_policy: str | None = None

    effective_from: datetime | None = None
    effective_to: datetime | None = None
    recorded_at: datetime | None = None
    retired_at: datetime | None = None
    supersedes_id: UUID | None = None
    superseded_by_id: UUID | None = None

    status: str | None = None

    test_fixtures: list[Any] | None = None
    test_fixtures_schema_name: str | None = None
    test_fixtures_schema_version: int | None = None

    source_location_ids: list[UUID] | None = None

    notes: str | None = None


class RuleVersionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    rule_id: UUID
    status: str

    requirement_version_id: UUID | None

    inputs: list[Any] | None
    inputs_schema_name: str | None
    inputs_schema_version: int | None

    condition: dict[str, Any]
    condition_schema_name: str | None
    condition_schema_version: int | None

    unknown_behavior: str

    output_type: str

    author_user_id: UUID | None
    reviewer_user_id: UUID | None
    verified_at: datetime | None
    approval_policy: str | None

    effective_from: datetime | None
    effective_to: datetime | None
    recorded_at: datetime | None
    retired_at: datetime | None
    supersedes_id: UUID | None
    superseded_by_id: UUID | None

    test_fixtures: list[Any] | None
    test_fixtures_schema_name: str | None
    test_fixtures_schema_version: int | None

    source_location_ids: list[UUID]

    notes: str | None
