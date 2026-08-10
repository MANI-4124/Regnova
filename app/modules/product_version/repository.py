from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository import BaseRepository

from .models import ProductVersion, ProductVersionStatus


class ProductVersionRepository(
    BaseRepository[ProductVersion],
):
    """
    Product version repository.
    """

    def __init__(
        self,
        db: Session,
    ):
        super().__init__(
            db,
            ProductVersion,
        )

    def get_all(
        self,
        organization_id: UUID,
        product_id: UUID,
    ) -> list[ProductVersion]:

        statement = (
            select(ProductVersion)
            .where(
                ProductVersion.organization_id == organization_id,
                ProductVersion.product_id == product_id,
                ProductVersion.is_active.is_(True),
            )
            .order_by(
                ProductVersion.created_at.desc(),
            )
        )

        return list(
            self.db.scalars(statement)
        )

    def get_by_id(
        self,
        organization_id: UUID,
        product_id: UUID,
        version_id: UUID,
    ) -> ProductVersion | None:

        statement = (
            select(ProductVersion)
            .where(
                ProductVersion.id == version_id,
                ProductVersion.organization_id == organization_id,
                ProductVersion.product_id == product_id,
            )
        )

        return self.db.scalar(statement)

    def get_by_version(
        self,
        organization_id: UUID,
        product_id: UUID,
        version: str,
    ) -> ProductVersion | None:

        statement = (
            select(ProductVersion)
            .where(
                ProductVersion.organization_id == organization_id,
                ProductVersion.product_id == product_id,
                ProductVersion.version == version,
            )
        )

        return self.db.scalar(statement)

    def get_current(
        self,
        organization_id: UUID,
        product_id: UUID,
    ) -> ProductVersion | None:
        """
        Most recently created APPROVED version - computed, not stored.
        """

        statement = (
            select(ProductVersion)
            .where(
                ProductVersion.organization_id == organization_id,
                ProductVersion.product_id == product_id,
                ProductVersion.status == ProductVersionStatus.APPROVED.value,
                ProductVersion.is_active.is_(True),
            )
            .order_by(
                ProductVersion.created_at.desc(),
            )
            .limit(1)
        )

        return self.db.scalar(statement)
