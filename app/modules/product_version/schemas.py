from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductVersionCreate(BaseModel):

    version: str

    # Added by the category-scoping fix (see CLAUDE.md "Category
    # scoping") - required, no default. Every requirement_version a
    # release eventually pins against this product version's category
    # must match it exactly.
    category: str

    status: str | None = None

    notes: str | None = None


class ProductVersionUpdate(BaseModel):
    # category is deliberately NOT editable here - immutable once set,
    # same as ProductMarketState.jurisdiction; a genuine reclassification
    # is a new ProductVersion, not an edit to an existing one.

    status: str | None = None

    notes: str | None = None

    is_active: bool | None = None


class ProductVersionResponse(BaseModel):

    model_config = ConfigDict(
        from_attributes=True,
    )

    id: UUID

    organization_id: UUID

    product_id: UUID

    version: str

    category: str

    status: str

    notes: str | None

    is_active: bool

    released_at: datetime | None
