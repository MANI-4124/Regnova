from __future__ import annotations

from app.common.exceptions import NotFoundException


class StateSnapshotNotFound(NotFoundException):
    error_code = "STATE_SNAPSHOT_NOT_FOUND"

    def __init__(self):
        super().__init__("State snapshot not found")
