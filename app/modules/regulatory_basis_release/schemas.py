from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RegulatoryBasisReleaseCreate(BaseModel):

    jurisdiction: str
    market: str
    status: str | None = None

    configuration: dict[str, Any] | None = None
    configuration_schema_name: str | None = None
    configuration_schema_version: int | None = None

    effective_from: datetime | None = None
    effective_to: datetime | None = None

    supersedes_id: UUID | None = None

    source_version_ids: list[UUID] | None = None
    requirement_version_ids: list[UUID] | None = None
    rule_version_ids: list[UUID] | None = None

    notes: str | None = None


class RegulatoryBasisReleaseUpdate(BaseModel):
    """
    Deliberately narrow - unlike every other Update schema in this
    codebase (which mirrors Create plus workflow fields), this one
    excludes jurisdiction/market/configuration/the three *_version_ids/
    supersedes_id/effective_from, since those define the immutable
    content identity of the release. C9.1 calls Release immutable
    outright, a stronger framing than "immutable once verified" for
    Source/Requirement/Rule Versions. See CLAUDE.md.
    """

    status: str | None = None
    notes: str | None = None
    reviewer_user_id: UUID | None = None
    verified_at: datetime | None = None
    retired_at: datetime | None = None
    superseded_by_id: UUID | None = None
    effective_to: datetime | None = None


class RegulatoryBasisReleaseResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    jurisdiction: str
    market: str
    status: str

    content_hash: str

    configuration: dict[str, Any] | None
    configuration_schema_name: str | None
    configuration_schema_version: int | None

    author_user_id: UUID | None
    reviewer_user_id: UUID | None
    verified_at: datetime | None

    effective_from: datetime | None
    effective_to: datetime | None
    recorded_at: datetime | None
    retired_at: datetime | None
    activated_at: datetime | None
    supersedes_id: UUID | None
    superseded_by_id: UUID | None

    source_version_ids: list[UUID]
    requirement_version_ids: list[UUID]
    rule_version_ids: list[UUID]

    notes: str | None
