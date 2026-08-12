from app.common.exceptions import ConflictException, NotFoundException


class ProductMarketStateNotFound(NotFoundException):
    """
    Product market state does not exist.
    """

    def __init__(self):
        super().__init__(
            "Product market state not found."
        )


class ProductMarketStateIneligibleProductVersion(ConflictException):
    """
    Referenced product version is not active.
    """

    def __init__(self):
        super().__init__(
            "This product version is not active and cannot be referenced "
            "by a product market state."
        )


class ProductMarketStateAlreadyActive(ConflictException):
    """
    An active state already exists for this product/market (surfaces on
    the update() race path - reactivating a row into a conflict with
    another that became active in the meantime).
    """

    def __init__(self):
        super().__init__(
            "An active product market state already exists for this "
            "product/market."
        )
