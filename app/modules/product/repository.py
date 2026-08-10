from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import Product


class ProductRepository(
    BaseRepository[Product],
):
    """
    Product repository.
    """

    def __init__(
        self,
        db: Session,
    ):
        super().__init__(
            db,
            Product,
        )

    def get_all(
        self,
        organization_id: UUID,
    ) -> list[Product]:

        statement = (
            select(Product)
            .where(
                Product.organization_id == organization_id,
                Product.is_active.is_(True),
            )
            .order_by(
                Product.created_at.desc(),
            )
        )

        return list(
            self.db.scalars(statement)
        )

    def get_by_id(
        self,
        organization_id: UUID,
        product_id: UUID,
    ) -> Product | None:

        statement = (
            select(Product)
            .where(
                Product.id == product_id,
                Product.organization_id == organization_id,
            )
        )

        return self.db.scalar(statement)