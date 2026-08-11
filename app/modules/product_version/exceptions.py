from app.common.exceptions import ConflictException, NotFoundException


class ProductVersionNotFound(NotFoundException):
    """
    Product version does not exist.
    """

    def __init__(self):
        super().__init__(
            "Product version not found."
        )


class ProductVersionAlreadyExists(ConflictException):
    """
    A version with this label already exists for this product.
    """

    def __init__(self):
        super().__init__(
            "A version with this label already exists for this product."
        )


class ProductVersionAlreadyPublished(ConflictException):
    """
    This product version has already been published.
    """

    def __init__(self):
        super().__init__(
            "This product version has already been published."
        )
