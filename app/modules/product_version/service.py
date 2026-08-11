from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.audit.repository import OutboxRepository
from app.modules.product.exceptions import ProductNotFound
from app.modules.product.repository import ProductRepository

from .exceptions import (
    ProductVersionAlreadyExists,
    ProductVersionAlreadyPublished,
    ProductVersionNotFound,
)
from .models import ProductVersion, ProductVersionStatus
from .repository import ProductVersionRepository
from .schemas import (
    ProductVersionCreate,
    ProductVersionUpdate,
)


class ProductVersionService:
    """
    Product version service.
    """

    def __init__(
        self,
        db: Session,
    ):
        self.db = db
        self.repository = ProductVersionRepository(
            db,
        )
        self.products = ProductRepository(
            db,
        )
        self.outbox = OutboxRepository(
            db,
        )

    def _get_product_or_404(
        self,
        organization_id: UUID,
        product_id: UUID,
    ):
        product = self.products.get_by_id(
            organization_id,
            product_id,
        )

        if product is None:
            raise ProductNotFound()

        return product

    def get_all(
        self,
        organization_id: UUID,
        product_id: UUID,
    ) -> list[ProductVersion]:

        self._get_product_or_404(
            organization_id,
            product_id,
        )

        return self.repository.get_all(
            organization_id,
            product_id,
        )

    def get_by_id(
        self,
        organization_id: UUID,
        product_id: UUID,
        version_id: UUID,
    ) -> ProductVersion:

        self._get_product_or_404(
            organization_id,
            product_id,
        )

        version = self.repository.get_by_id(
            organization_id,
            product_id,
            version_id,
        )

        if version is None:
            raise ProductVersionNotFound()

        return version

    def get_current(
        self,
        organization_id: UUID,
        product_id: UUID,
    ) -> ProductVersion:

        self._get_product_or_404(
            organization_id,
            product_id,
        )

        version = self.repository.get_current(
            organization_id,
            product_id,
        )

        if version is None:
            raise ProductVersionNotFound()

        return version

    def create(
        self,
        organization_id: UUID,
        product_id: UUID,
        payload: ProductVersionCreate,
    ) -> ProductVersion:

        self._get_product_or_404(
            organization_id,
            product_id,
        )

        if self.repository.get_by_version(
            organization_id,
            product_id,
            payload.version,
        ):
            raise ProductVersionAlreadyExists()

        version = ProductVersion(
            organization_id=organization_id,
            product_id=product_id,
            version=payload.version,
            status=payload.status or ProductVersionStatus.DRAFT.value,
            notes=payload.notes,
        )

        self.repository.create(
            version,
        )

        self.db.commit()

        return version

    def update(
        self,
        organization_id: UUID,
        product_id: UUID,
        version_id: UUID,
        payload: ProductVersionUpdate,
    ) -> ProductVersion:

        version = self.get_by_id(
            organization_id,
            product_id,
            version_id,
        )

        data = payload.model_dump(
            exclude_unset=True,
        )

        for field, value in data.items():
            setattr(
                version,
                field,
                value,
            )

        self.repository.update(
            version,
        )

        self.db.commit()

        return version

    def delete(
        self,
        organization_id: UUID,
        product_id: UUID,
        version_id: UUID,
    ) -> None:

        version = self.get_by_id(
            organization_id,
            product_id,
            version_id,
        )

        version.is_active = False

        self.repository.update(
            version,
        )

        self.db.commit()

    def publish(
        self,
        organization_id: UUID,
        product_id: UUID,
        version_id: UUID,
        correlation_id: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> ProductVersion:

        version = self.get_by_id(
            organization_id,
            product_id,
            version_id,
        )

        if version.released_at is not None:
            raise ProductVersionAlreadyPublished()

        version.released_at = datetime.now(timezone.utc)

        self.repository.update(
            version,
        )

        self.outbox.append(
            organization_id=organization_id,
            event_type="ProductVersionPublished",
            schema_version=1,
            payload={
                "product_id": str(product_id),
                "product_version_id": str(version.id),
                "version": version.version,
                # delta omitted - FR-02 version-compare isn't built yet
            },
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )

        self.db.commit()

        return version
