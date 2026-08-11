import uuid
from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db_session(
    request: Request,
) -> Generator[Session, None, None]:
    """
    Returns a database session per request.
    """

    session = request.app.state.database.session_factory()

    try:
        yield session
    finally:
        session.close()


def get_correlation_id(
    request: Request,
) -> str:
    """
    Returns the correlation ID stashed on request.state by
    CorrelationIdMiddleware.
    """

    return getattr(
        request.state,
        "correlation_id",
        None,
    ) or str(uuid.uuid4())