from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from .exceptions import ProductNotFound
from .models import Product
from .repository import ProductRepository
from .schemas import (
    ProductCreate,
    ProductUpdate,
)


class ProductService:
    """
    Product service.
    """

    def __init__(
        self,
        db: Session,
    ):
        self.db = db
        self.repository = ProductRepository(
            db,
        )

    def get_all(
        self,
        organization_id: UUID,
    ):
        return self.repository.get_all(
            organization_id,
        )

    def get_by_id(
        self,
        organization_id: UUID,
        product_id: UUID,
    ):
        product = self.repository.get_by_id(
            organization_id,
            product_id,
        )

        if product is None:
            raise ProductNotFound()

        return product

    def create(
        self,
        organization_id: UUID,
        payload: ProductCreate,
    ):
        product = Product(
            organization_id=organization_id,
            name=payload.name,
            brand=payload.brand,
            description=payload.description,
        )

        self.repository.create(
            product,
        )

        self.db.commit()

        return product

    def update(
        self,
        organization_id: UUID,
        product_id: UUID,
        payload: ProductUpdate,
    ):
        product = self.get_by_id(
            organization_id,
            product_id,
        )

        data = payload.model_dump(
            exclude_unset=True,
        )

        for field, value in data.items():
            setattr(
                product,
                field,
                value,
            )

        self.repository.update(
            product,
        )

        self.db.commit()

        return product

    def delete(
        self,
        organization_id: UUID,
        product_id: UUID,
    ) -> None:

        product = self.get_by_id(
            organization_id,
            product_id,
        )

        product.is_active = False

        self.repository.update(
            product,
        )

        self.db.commit()