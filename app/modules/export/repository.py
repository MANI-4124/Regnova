from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Export


class ExportRepository(BaseRepository[Export]):
    """
    Repository for Export. Organization-scoped like Document/Evidence/
    ProductMarketState for get_all/get_by_id (the customer-scoped read
    path) - plus get_by_id_unscoped, needed because a download request
    doesn't know in advance whether the export is a customer's own
    FINDINGS_CSV (org-scoped access check) or an internal reader's
    EVIDENCE_PACK_JSON (INTERNAL_REGULATORY tier check, no org match
    required) until the row itself is loaded and its export_type
    inspected - see ExportService.
    """

    def __init__(self, db: Session):
        super().__init__(db, Export)

    def get_all(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
    ) -> list[Export]:
        statement = (
            select(Export)
            .where(
                Export.organization_id == organization_id,
                Export.product_market_state_id == product_market_state_id,
            )
            .order_by(Export.created_at.desc())
        )

        return list(self.db.scalars(statement))

    def get_by_id_for_org(
        self,
        organization_id: UUID,
        export_id: UUID,
    ) -> Export | None:
        statement = select(Export).where(
            Export.id == export_id,
            Export.organization_id == organization_id,
        )

        return self.db.scalar(statement)

    def get_by_id_unscoped(self, export_id: UUID) -> Export | None:
        return self.db.get(Export, export_id)
