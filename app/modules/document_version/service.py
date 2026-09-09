from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.modules.audit.repository import OutboxRepository
from app.modules.document.exceptions import DocumentNotFound
from app.modules.document.repository import DocumentRepository
from app.modules.evidence.repository import EvidenceRepository
from app.scanning import MalwareScanner, ScanOutcome, ScannerUnavailable
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
        scanner: MalwareScanner,
        settings: Settings | None = None,
    ):
        self.db = db
        self.storage = storage
        self.scanner = scanner
        self.settings = settings or get_settings()
        self.documents = DocumentRepository(db)
        self.repository = DocumentVersionRepository(db)
        self.evidence = EvidenceRepository(db)
        self.outbox = OutboxRepository(db)

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
        correlation_id: str | None = None,
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
            # SCANNING, not REVIEW_REQUIRED - a version now only reaches
            # REVIEW_REQUIRED after a clean scan. See CLAUDE.md "Malware
            # scanning".
            status=DocumentVersionStatus.SCANNING.value,
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

        # FR-14/Appendix 2's own canonical name, used verbatim - a
        # future consumer registered against exactly this event_type
        # (e.g. C14's "Evidence matching, consistency checks" for
        # DocumentVersionVerified) stays aligned with the spec's own
        # vocabulary. Not emitted for the checksum-dedup no-op above -
        # nothing changed, nothing to record.
        self.outbox.append(
            organization_id=organization_id,
            event_type="DocumentVersionUploaded",
            schema_version=1,
            payload={
                "document_id": str(document_id),
                "document_version_id": str(version.id),
                "version_number": version.version_number,
                "content_type": content_type,
                "size_bytes": version.size_bytes,
                "checksum": checksum,
                "supersedes_id": str(current.id) if current else None,
            },
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )

        # Committed here, BEFORE the scan runs - mirrors AssessmentRun.RUNNING/
        # Export.GENERATING's own "a crash must still leave a visible,
        # terminal-or-retryable record" precedent. SCANNING now has a
        # genuine, measurable duration (a network round trip, possibly
        # a timeout), unlike the excluded UPLOADING state.
        self.db.commit()

        self._run_scan_and_transition(
            version,
            content,
            organization_id=organization_id,
            document_id=document_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

        return version

    def retry_scan(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        *,
        actor_user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> DocumentVersion:
        """
        AC-FR-04-03: retried idempotently, without creating another
        document version - re-reads the SAME stored bytes via checksum
        (content-addressed, never re-uploaded) and re-attempts the scan
        on the SAME row. Valid from FAILED (the scanner couldn't be
        reached last time) or SCANNING (a version stuck there from a
        crashed request is operationally the same problem - a human
        needs to kick it again either way, see CLAUDE.md "Malware
        scanning").
        """
        version = self.get_by_id(organization_id, document_id, version_id)

        if version.status not in (
            DocumentVersionStatus.FAILED.value,
            DocumentVersionStatus.SCANNING.value,
        ):
            raise DocumentVersionTransitionNotAllowed(
                "retry-scan is only allowed while the document version "
                "is FAILED or SCANNING.",
            )

        content = self.storage.get(version.checksum)

        self._run_scan_and_transition(
            version,
            content,
            organization_id=organization_id,
            document_id=document_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )

        return version

    def _run_scan_and_transition(
        self,
        version: DocumentVersion,
        content: bytes,
        *,
        organization_id: UUID,
        document_id: UUID,
        actor_user_id: UUID | None,
        correlation_id: str | None,
    ) -> None:
        """
        The one place SCANNING resolves to REVIEW_REQUIRED/QUARANTINED/
        FAILED, called from both create() (the first attempt) and
        retry_scan() (any subsequent one) - so the transition logic
        itself never has to know which caller it's serving. Fail-
        closed throughout: a version only ever reaches REVIEW_REQUIRED
        after an actual CLEAN result, never as a side effect of the
        scanner being unavailable. See CLAUDE.md "Malware scanning".
        """
        from_status = version.status

        try:
            result = self.scanner.scan(content)
        except ScannerUnavailable as exc:
            version.status = DocumentVersionStatus.FAILED.value
            version.scan_error = str(exc)
            self.repository.update(version)

            # New event type, diverging from the AssessmentRun/Export
            # "no event on FAILED" precedent - see CLAUDE.md "Malware
            # scanning": document quarantine/scan backlog is a named P1
            # operational signal the spec calls out directly, unlike
            # export-generation failures.
            self.outbox.append(
                organization_id=organization_id,
                event_type="DocumentVersionScanFailed",
                schema_version=1,
                payload={
                    "document_id": str(document_id),
                    "document_version_id": str(version.id),
                    "from_status": from_status,
                    "scan_error": version.scan_error,
                },
                correlation_id=correlation_id,
                actor_user_id=actor_user_id,
            )
            self.db.commit()
            return

        if result.outcome == ScanOutcome.INFECTED:
            version.status = DocumentVersionStatus.QUARANTINED.value
            version.malware_signature = result.signature_name
            version.scan_error = None
            version.review_note = (
                f"Automatically quarantined: malware detected ({result.signature_name})."
            )
            self.repository.update(version)
            # reviewed_by_user_id/reviewed_at deliberately stay null -
            # no human decided this, same "engine-authored, no actor"
            # precedent as FindingRevision.decided_by_user_id. Reuses
            # the existing DocumentVersionQuarantined event/builder -
            # no new tier/redaction logic needed, this IS a quarantine,
            # just an automated one.
            self._publish_reviewed(
                "DocumentVersionQuarantined", version, organization_id=organization_id,
                document_id=document_id, from_status=from_status,
                note=version.review_note, actor_user_id=None, correlation_id=correlation_id,
            )
            self.db.commit()
            return

        version.status = DocumentVersionStatus.REVIEW_REQUIRED.value
        version.scan_error = None
        self.repository.update(version)
        self.db.commit()

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
        correlation_id: str | None = None,
    ) -> DocumentVersion:
        version = self.get_by_id(organization_id, document_id, version_id)
        self._require_reviewable(version)
        from_status = version.status

        version.status = DocumentVersionStatus.VERIFIED.value
        version.reviewed_by_user_id = actor_user_id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_note = note

        self.repository.update(version)
        self._publish_reviewed(
            "DocumentVersionVerified", version, organization_id=organization_id,
            document_id=document_id, from_status=from_status, note=note,
            actor_user_id=actor_user_id, correlation_id=correlation_id,
        )
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
        correlation_id: str | None = None,
    ) -> DocumentVersion:
        version = self.get_by_id(organization_id, document_id, version_id)
        self._require_reviewable(version)
        from_status = version.status

        version.status = DocumentVersionStatus.REJECTED.value
        version.reviewed_by_user_id = actor_user_id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_note = note

        self.repository.update(version)
        self._publish_reviewed(
            "DocumentVersionRejected", version, organization_id=organization_id,
            document_id=document_id, from_status=from_status, note=note,
            actor_user_id=actor_user_id, correlation_id=correlation_id,
        )
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
        correlation_id: str | None = None,
    ) -> DocumentVersion:
        version = self.get_by_id(organization_id, document_id, version_id)
        self._require_reviewable(version)
        from_status = version.status

        version.status = DocumentVersionStatus.QUARANTINED.value
        version.reviewed_by_user_id = actor_user_id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_note = note

        self.repository.update(version)
        self._publish_reviewed(
            "DocumentVersionQuarantined", version, organization_id=organization_id,
            document_id=document_id, from_status=from_status, note=note,
            actor_user_id=actor_user_id, correlation_id=correlation_id,
        )
        self.db.commit()

        return version

    def _publish_reviewed(
        self,
        event_type: str,
        version: DocumentVersion,
        *,
        organization_id: UUID,
        document_id: UUID,
        from_status: str,
        note: str | None,
        actor_user_id: UUID | None,
        correlation_id: str | None,
    ) -> None:
        """
        Three distinct event types (DocumentVersionVerified is
        Appendix 2's own canonical name; Rejected/Quarantined are new,
        added alongside it) rather than one parameterized event - unlike
        Finding's seven transitions collapsing into one
        FindingDecisionChanged, there are only three fixed, mutually
        exclusive outcomes here, and matching Appendix 2's own verbatim
        name for the one it already defines seemed more valuable than
        parameterizing three names into one. See CLAUDE.md "Audit log".
        """
        self.outbox.append(
            organization_id=organization_id,
            event_type=event_type,
            schema_version=1,
            payload={
                "document_id": str(document_id),
                "document_version_id": str(version.id),
                "from_status": from_status,
                "to_status": version.status,
                "note": note,
            },
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )


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
        self.outbox = OutboxRepository(db)

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
        correlation_id: str | None = None,
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

        # Closes AC-FR-04-02 ("corrections create a revision and an
        # audit event") - this event type was previously unsatisfiable:
        # nothing existed to write an audit event to until this ticket.
        # "Revised" rather than "Corrected" since this fires for the
        # FIRST entry too (revision_number == 1), not only genuine
        # corrections. Customer-visible - see CLAUDE.md "Audit log" for
        # why a document's own org has no internal/customer line to
        # draw here at all.
        self.outbox.append(
            organization_id=organization_id,
            event_type="DocumentFieldRevised",
            schema_version=1,
            payload={
                "document_id": str(document_id),
                "document_version_id": str(version_id),
                "field_key": field_key,
                "revision_number": next_revision_number,
                "value": value,
                "confidence": confidence,
                "method": "MANUAL",
            },
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )

        self.db.commit()
        self.db.refresh(field)

        return field
