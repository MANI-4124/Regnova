from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductMarketStateCreate(BaseModel):

    product_version_id: UUID
    market: str
    # Added by the category-scoping fix (see CLAUDE.md "Category
    # scoping") - the real pinning key. `market` is kept, required, but
    # non-authoritative; auto-pin resolution reads jurisdiction (+ the
    # pinned product version's own category) instead.
    jurisdiction: str


class ProductMarketStateUpdate(BaseModel):

    product_version_id: UUID | None = None
    regulatory_basis_release_id: UUID | None = None
    gate: str | None = None
    status: str | None = None


class ProductMarketStateResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID
    organization_id: UUID
    product_id: UUID
    product_version_id: UUID | None
    market: str
    jurisdiction: str
    regulatory_basis_release_id: UUID | None
    gate: str
    status: str
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
