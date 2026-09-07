from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentVersionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    document_id: UUID
    organization_id: UUID
    version_number: int
    checksum: str
    storage_backend: str
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    supersedes_id: UUID | None
    superseded_by_id: UUID | None
    uploaded_by_user_id: UUID | None
    reviewed_by_user_id: UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DocumentVersionReviewRequest(BaseModel):
    """
    Body for verify - note is optional (an approval doesn't need a
    rationale the way a rejection does).
    """

    note: str | None = None


class DocumentVersionRejectRequest(BaseModel):
    """
    Body for reject/quarantine - note is required and non-empty,
    matching the D6.1 rationale-requirement precedent already used for
    content-review reject().
    """

    note: str = Field(min_length=1)


class DocumentFieldSetRequest(BaseModel):

    value: Any

    # Defaults to null, not 1.0 - see DocumentFieldRevision's own
    # docstring for the reasoning.
    confidence: float | None = None

    location: dict[str, Any] | None = None


class DocumentFieldRevisionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    revision_number: int
    value: Any
    confidence: float | None
    method: str
    location: dict[str, Any] | None
    entered_by_user_id: UUID | None
    created_at: datetime


class DocumentFieldResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    document_version_id: UUID
    field_key: str
    revisions: list[DocumentFieldRevisionResponse]
