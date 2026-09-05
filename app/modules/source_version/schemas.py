from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SourceVersionCreate(BaseModel):

    title: str
    issuing_authority: str
    jurisdiction: str
    tier: int
    source_type: str
    official_url: str | None = None

    file_checksum: str | None = None
    canonical_text_checksum: str | None = None
    language: str | None = None
    translation_status: str | None = None
    retrieval_method: str | None = None

    published_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    retrieved_at: datetime | None = None

    license_notes: str | None = None
    usage_restrictions: str | None = None
    is_full_text_displayable: bool | None = None

    notes: str | None = None


class SourceVersionUpdate(BaseModel):

    title: str | None = None
    issuing_authority: str | None = None
    jurisdiction: str | None = None
    tier: int | None = None
    source_type: str | None = None
    official_url: str | None = None

    file_checksum: str | None = None
    canonical_text_checksum: str | None = None
    language: str | None = None
    translation_status: str | None = None
    retrieval_method: str | None = None

    published_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    retrieved_at: datetime | None = None
    recorded_at: datetime | None = None
    retired_at: datetime | None = None
    supersedes_id: UUID | None = None
    superseded_by_id: UUID | None = None

    # status/author_user_id/reviewer_user_id/verified_at/activated_at
    # are deliberately NOT editable here - see RequirementVersionUpdate's
    # own comment and CLAUDE.md "Regulatory content approval workflow".

    license_notes: str | None = None
    usage_restrictions: str | None = None
    is_full_text_displayable: bool | None = None

    notes: str | None = None


class SourceVersionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    source_id: UUID

    title: str
    issuing_authority: str
    jurisdiction: str
    tier: int
    source_type: str
    official_url: str | None

    file_checksum: str | None
    canonical_text_checksum: str | None
    language: str | None
    translation_status: str
    retrieval_method: str | None

    published_at: datetime | None
    effective_from: datetime | None
    effective_to: datetime | None
    retrieved_at: datetime | None
    verified_at: datetime | None
    recorded_at: datetime | None
    retired_at: datetime | None
    activated_at: datetime | None
    supersedes_id: UUID | None
    superseded_by_id: UUID | None

    status: str
    author_user_id: UUID | None
    reviewer_user_id: UUID | None

    license_notes: str | None
    usage_restrictions: str | None
    is_full_text_displayable: bool

    notes: str | None
