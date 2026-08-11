from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-Id"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Reads X-Correlation-Id from the incoming request (generating one if
    absent), stashes it on request.state, and echoes it back on the
    response so callers can round-trip it across services.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = (
            request.headers.get(CORRELATION_ID_HEADER)
            or str(uuid.uuid4())
        )

        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        return response
