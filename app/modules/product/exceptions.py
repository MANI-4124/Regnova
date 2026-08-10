from app.common.exceptions import NotFoundException


class ProductNotFound(NotFoundException):
    def __init__(self):
        super().__init__(
            "Product not found."
        )
