import uuid
from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.storage import DocumentStorage, LocalFilesystemStorage


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


def get_document_storage() -> DocumentStorage:
    """
    A plain Depends()-based provider, not app.state - mirrors
    get_db_session's own override-ability: tests replace this via
    app.dependency_overrides the same way they already do for the DB
    session, rather than needing a real filesystem under the repo root.
    """

    settings = get_settings()

    if settings.document_storage_backend == "local":
        return LocalFilesystemStorage(settings.document_storage_root)

    raise RuntimeError(
        f"Unknown document_storage_backend: {settings.document_storage_backend!r}",
    )