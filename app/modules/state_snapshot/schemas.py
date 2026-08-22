from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StateSnapshotResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    product_market_state_id: UUID
    product_version_id: UUID
    regulatory_basis_release_id: UUID
    assessment_run_id: UUID | None

    overall_gate: str
    raw_progress: float
    displayed_progress: float
    highest_open_severity: str | None
    readiness_reason_codes: list[Any]
    outstanding_action_count: int

    dimension_summary: dict[str, Any]
    unresolved_severity_counts: dict[str, Any]

    engine_build: str

    is_current: bool
    stale_reason: str | None
    superseded_by_snapshot_id: UUID | None

    created_at: datetime
