import uuid
from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.analysis import SemanticAnalyzer, build_semantic_analyzer
from app.core.settings import get_settings
from app.extraction import DocumentExtractor, build_document_extractor
from app.scanning import ClamAVScanner, MalwareScanner, NoOpScanner
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


def get_malware_scanner() -> MalwareScanner:
    """
    Same plain Depends()-based, override-able shape as
    get_document_storage - tests replace this via
    app.dependency_overrides instead of needing a real ClamAV
    container. See CLAUDE.md "Malware scanning".
    """

    settings = get_settings()

    if settings.malware_scanner_backend == "noop":
        return NoOpScanner()

    if settings.malware_scanner_backend == "clamav":
        return ClamAVScanner(
            host=settings.clamav_host,
            port=settings.clamav_port,
            timeout=settings.clamav_timeout_seconds,
        )

    raise RuntimeError(
        f"Unknown malware_scanner_backend: {settings.malware_scanner_backend!r}",
    )


def get_semantic_analyzer() -> SemanticAnalyzer:
    """
    Same plain Depends()-based, override-able shape as get_malware_scanner /
    get_document_storage - tests replace this via app.dependency_overrides
    instead of reaching a real LLM. Default resolution
    (Settings.semantic_analyzer_backend == "stub") is StubSemanticAnalyzer,
    always the benign answer, so no existing test's behaviour changes. See
    app/analysis/ and CLAUDE.md "Semantic analysis (Claims + Label)".
    """
    return build_semantic_analyzer(get_settings())


def get_document_extractor() -> DocumentExtractor:
    """
    Same plain Depends()-based, override-able shape as the other three
    technical-layer providers above - tests replace this via
    app.dependency_overrides instead of reaching a real vision model.
    Default resolution (Settings.document_extractor_backend == "noop")
    is NoOpExtractor, always an empty result, so no existing test's
    behaviour changes. See app/extraction/ and CLAUDE.md "Document
    extraction".
    """
    return build_document_extractor(get_settings())