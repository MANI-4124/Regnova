from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .models import ExportType


class ExportCreate(BaseModel):
    """
    The customer path (POST /exports) - organization_id is always
    current_user.organization_id, never accepted here. export_type is
    pinned to a Literal so this schema structurally cannot request
    EVIDENCE_PACK_JSON even if a caller tries.
    """

    export_type: Literal[ExportType.FINDINGS_CSV.value] = ExportType.FINDINGS_CSV.value
    product_market_state_id: UUID


class InternalExportCreate(BaseModel):
    """
    The internal path (POST /exports/internal) - the second deliberate,
    narrow exception to "organization_id is never client-supplied". See
    CLAUDE.md "Deliberate organization_id exceptions".
    """

    export_type: Literal[ExportType.EVIDENCE_PACK_JSON.value] = ExportType.EVIDENCE_PACK_JSON.value
    organization_id: UUID
    product_market_state_id: UUID
    state_snapshot_id: UUID | None = None


class ExportResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    export_type: str
    product_market_state_id: UUID
    state_snapshot_id: UUID | None
    status: str
    content_type: str | None
    size_bytes: int | None
    error_message: str | None
    requested_by_user_id: UUID | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
