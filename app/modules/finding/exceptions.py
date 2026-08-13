from __future__ import annotations

from app.common.exceptions import NotFoundException


class FindingNotFound(NotFoundException):
    error_code = "FINDING_NOT_FOUND"

    def __init__(self):
        super().__init__("Finding not found")
