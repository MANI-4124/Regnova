from __future__ import annotations

from app.common.exceptions import NotFoundException


class NotificationNotFound(NotFoundException):
    """
    Notification does not exist, OR exists but belongs to a different
    recipient - the same information-hiding convention this codebase
    uses for cross-org 404s elsewhere (404, never 403, so a caller can't
    distinguish "not yours" from "doesn't exist").
    """

    error_code = "NOTIFICATION_NOT_FOUND"

    def __init__(self):
        super().__init__("Notification not found.")
