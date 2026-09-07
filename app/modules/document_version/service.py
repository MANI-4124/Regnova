from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.modules.document.exceptions import DocumentNotFound
from app.modules.document.repository import DocumentRepository
from app.modules.evidence.repository import EvidenceRepository
from app.storage import DocumentStorage

from .exceptions import (
    DocumentVersionInvalidFileType,
    DocumentVersionNotEditable,
    DocumentVersionNotFound,
    DocumentVersionTooLarge,
    DocumentVersionTransitionNotAllowed,
)
from .models import (
    DocumentField,
    DocumentFieldRevision,
    DocumentVersion,
    DocumentVersionStatus,
)
from .repository import (
    DocumentFieldRepository,
    DocumentFieldRevisionRepository,
    DocumentVersionRepository,
)

# C8.1's V1 formats. DOCX/XLSX share the OOXML/ZIP container magic
# number, so they can't be told apart from bytes alone without opening
# the archive - that disambiguation is left to the client-declared
# content type, gated on the bytes at least being a real ZIP (see
# sniff_content_type). CSV has no magic number at all.
_OOXML_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
}

_CSV_CONTENT_TYPES = {
    "text/csv",
    "application/vnd.ms-excel",
}

_MAGIC_SIGNATURES: dict[bytes, str] = {
    b"%PDF-": "application/pdf",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}

_ZIP_SIGNATURE = b"PK\x03\x04"


def sniff_content_type(content: bytes, declared_content_type: str) -> str:
    """
    Validates the ACTUAL bytes, not just the client-supplied
    Content-Type header, which is trivially spoofable - AC-FR-04's own
    "MIME mismatch" edge case is exactly this. PDF/PNG/JPEG have real
    magic numbers and are sniffed directly, overriding whatever the
    client claimed. DOCX/XLSX (both ZIP containers) and CSV (no magic
    number at all) fall back to trusting the declared content_type
    provided the bytes are at least consistent with it - a real ZIP
    signature for the two OOXML types, decodable text for CSV. Full
    docx-vs-xlsx disambiguation would need to inspect the zip's
    internal manifest, which is more than a storage-and-versioning
    ticket should take on - a real, if narrow, gap, not silently
    pretended away.

    Written without a new dependency (no python-magic) - awkward on
    Windows, and unnecessary for exactly these six formats.
    """

    for signature, content_type in _MAGIC_SIGNATURES.items():
        if content.startswith(signature):
            return content_type

    if declared_content_type in _OOXML_CONTENT_TYPES:
        if content.startswith(_ZIP_SIGNATURE):
            return declared_content_type
        raise DocumentVersionInvalidFileType(declared_content_type)

    if declared_content_type in _CSV_CONTENT_TYPES:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentVersionInvalidFileType(declared_content_type) from exc
        return "text/csv"

    raise DocumentVersionInvalidFileType(declared_content_type)


class DocumentVersionService:
    """
    Business logic for DocumentVersion - upload, supersession,
    checksum-based no-op dedup, and the verify/reject/quarantine
    review transitions. See CLAUDE.md "Document storage and
    versioning".
    """

    def __init__(
        self,
        db: Session,
        storage: DocumentStorage,
        settings: Settings | None = None,
    ):
        self.db = db
        self.storage = storage
        self.settings = settings or get_settings()
        self.documents = DocumentRepository(db)
        self.repository = DocumentVersionRepository(db)
        self.evidence = EvidenceRepository(db)

    def _get_document_or_404(self, organization_id: UUID, document_id: UUID):
        document = self.documents.get_by_id(organization_id, document_id)

        if document is None:
            raise DocumentNotFound()

        return document

    def get_all(
        self,
        organization_id: UUID,
        document_id: UUID,
    ) -> list[DocumentVersion]:
        self._get_document_or_404(organization_id, document_id)

        return self.repository.get_all(organization_id, document_id)

    def get_by_id(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersion:
        self._get_document_or_404(organization_id, document_id)

        version = self.repository.get_by_id(organization_id, document_id, version_id)

        if version is None:
            raise DocumentVersionNotFound()

        return version

    def create(
        self,
        organization_id: UUID,
        document_id: UUID,
        *,
        filename: str,
        declared_content_type: str,
        content: bytes,
        notes: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> DocumentVersion:
        self._get_document_or_404(organization_id, document_id)

        if len(content) > self.settings.document_max_size_bytes:
            raise DocumentVersionTooLarge(self.settings.document_max_size_bytes)

        content_type = sniff_content_type(content, declared_content_type)
        checksum = hashlib.sha256(content).hexdigest()

        current = self.repository.get_current(document_id)

        # Re-uploading byte-identical content for the SAME document is a
        # true no-op - matches the file-loader's own "unchanged content
        # is a no-op" precedent (see CLAUDE.md "File-based regulatory
        # content pipeline") - not a new version, not an error, nothing
        # written to storage or the DB.
        if current is not None and current.checksum == checksum:
            return current

        # Content-addressed - put() is naturally idempotent even if the
        # exact same bytes back a different Document elsewhere, which is
        # a legitimate, expected case (e.g. the same signed LOA reused).
        self.storage.put(checksum, content)

        next_version_number = self.repository.get_latest_version_number(document_id) + 1

        version = DocumentVersion(
            document_id=document_id,
            organization_id=organization_id,
            version_number=next_version_number,
            checksum=checksum,
            storage_backend=self.settings.document_storage_backend,
            original_filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            status=DocumentVersionStatus.REVIEW_REQUIRED.value,
            supersedes_id=current.id if current else None,
            uploaded_by_user_id=actor_user_id,
            notes=notes,
        )
        self.repository.create(version)

        if current is not None:
            current.superseded_by_id = version.id
            self.repository.update(current)

            # Stale-flagging, built now rather than deferred (see
            # CLAUDE.md "Document storage and versioning") - via
            # EvidenceRepository directly, not EvidenceService, same
            # "reach into the lower layer, don't import the whole
            # service" precedent as ProductMarketStateService flagging
            # StateSnapshot stale. Any Evidence still pointing at the
            # version this upload just replaced no longer reflects the
            # current file.
            self.evidence.mark_stale_for_document_version(
                current.id,
                "DOCUMENT_VERSION_SUPERSEDED",
            )

        self.db.commit()

        return version

    def _require_reviewable(self, version: DocumentVersion) -> None:
        if version.status != DocumentVersionStatus.REVIEW_REQUIRED.value:
            raise DocumentVersionTransitionNotAllowed()

    def verify(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        *,
        note: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> DocumentVersion:
        version = self.get_by_id(organization_id, document_id, version_id)
        self._require_reviewable(version)

        version.status = DocumentVersionStatus.VERIFIED.value
        version.reviewed_by_user_id = actor_user_id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_note = note

        self.repository.update(version)
        self.db.commit()

        return version

    def reject(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        *,
        note: str,
        actor_user_id: UUID | None = None,
    ) -> DocumentVersion:
        version = self.get_by_id(organization_id, document_id, version_id)
        self._require_reviewable(version)

        version.status = DocumentVersionStatus.REJECTED.value
        version.reviewed_by_user_id = actor_user_id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_note = note

        self.repository.update(version)
        self.db.commit()

        return version

    def quarantine(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        *,
        note: str,
        actor_user_id: UUID | None = None,
    ) -> DocumentVersion:
        version = self.get_by_id(organization_id, document_id, version_id)
        self._require_reviewable(version)

        version.status = DocumentVersionStatus.QUARANTINED.value
        version.reviewed_by_user_id = actor_user_id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_note = note

        self.repository.update(version)
        self.db.commit()

        return version


class DocumentFieldService:
    """
    Manual structured-field entry (FR-04's stand-in for OCR/extraction -
    see CLAUDE.md). Writes the exact {"value", "confidence"}-shaped
    revision history the future engine-wiring ticket will read directly.
    """

    def __init__(self, db: Session):
        self.db = db
        self.documents = DocumentRepository(db)
        self.versions = DocumentVersionRepository(db)
        self.fields = DocumentFieldRepository(db)
        self.revisions = DocumentFieldRevisionRepository(db)

    def _get_version_or_404(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> DocumentVersion:
        if self.documents.get_by_id(organization_id, document_id) is None:
            raise DocumentNotFound()

        version = self.versions.get_by_id(organization_id, document_id, version_id)

        if version is None:
            raise DocumentVersionNotFound()

        return version

    def get_all(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> list[DocumentField]:
        self._get_version_or_404(organization_id, document_id, version_id)

        return self.fields.get_all_for_version(version_id)

    def set_field(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        field_key: str,
        *,
        value: Any,
        confidence: float | None = None,
        location: dict[str, Any] | None = None,
        actor_user_id: UUID | None = None,
    ) -> DocumentField:
        version = self._get_version_or_404(organization_id, document_id, version_id)

        # Mirrors ContentReviewWorkflow.require_editable's DRAFT-only-
        # edit precedent - once verified/rejected/quarantined, a
        # version's recorded fields are a historical record, not a live
        # document to keep rewriting.
        if version.status != DocumentVersionStatus.REVIEW_REQUIRED.value:
            raise DocumentVersionNotEditable()

        field = self.fields.get_by_key(version_id, field_key)

        if field is None:
            field = DocumentField(
                document_version_id=version_id,
                field_key=field_key,
            )
            self.fields.create(field)

        next_revision_number = self.revisions.get_latest_revision_number(field.id) + 1

        revision = DocumentFieldRevision(
            document_field_id=field.id,
            revision_number=next_revision_number,
            value=value,
            confidence=confidence,
            method="MANUAL",
            location=location,
            entered_by_user_id=actor_user_id,
        )
        self.revisions.create(revision)

        self.db.commit()
        self.db.refresh(field)

        return field
