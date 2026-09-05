from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class ContentVersionTransitionRequest(BaseModel):
    """
    Body for verify/activate/reject - D6.1's rationale requirement,
    enforced as a required, non-empty field rather than the freely
    optional `notes` the old generic PATCH allowed.
    """

    rationale: str = Field(min_length=1)


class ContentVersionRef(BaseModel):
    """One item in a bulk-verify/bulk-activate request."""

    content_type: str
    content_id: UUID


class BulkContentReviewRequest(BaseModel):
    """
    Body for bulk-verify/bulk-activate. One rationale applies to the
    whole batch - deliberately NOT validated against any commit-hash
    format server-side: the rationale is the reviewer's own attestation,
    not a templated field the loader fills in for them. See CLAUDE.md
    "File-based regulatory content pipeline".
    """

    items: list[ContentVersionRef] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class BulkContentReviewItemResult(BaseModel):

    content_type: str
    content_id: UUID
    status: str  # "verified" | "activated" | "failed"
    error: str | None = None


class BulkContentReviewResponse(BaseModel):

    results: list[BulkContentReviewItemResult]
