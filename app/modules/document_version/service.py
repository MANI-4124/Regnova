from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings, get_settings
from app.extraction import (
    DocumentExtractionUnavailable,
    DocumentExtractor,
    EXTRACTION_SCHEMAS,
    GeminiDocumentExtractor,
)
from app.modules.audit.repository import OutboxRepository
from app.modules.document.exceptions import DocumentNotFound
from app.modules.document.repository import DocumentRepository
from app.modules.evidence.repository import EvidenceRepository
from app.modules.organization.service import require_organization_synthetic
from app.scanning import MalwareScanner, ScanOutcome, ScannerUnavailable
from app.storage import DocumentStorage

from .exceptions import (
    DocumentTypeHasNoExtractionSchema,
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
        extractor: DocumentExtractor,
        settings: Settings | None = None,
    ):
        self.db = db
        self.storage = storage
        self.scanner = scanner
        self.extractor = extractor
        self.settings = settings or get_settings()
        self.documents = DocumentRepository(db)
        self.repository = DocumentVersionRepository(db)
        self.evidence = EvidenceRepository(db)
        self.outbox = OutboxRepository(db)
        # Composed, not injected - DocumentFieldService only ever needs
        # db, and extraction needs its write_extracted_field() method
        # (see CLAUDE.md "Document extraction").
        self.field_service = DocumentFieldService(db)

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

        version.scan_error = None

        # Clean scan -> extraction, if this document_type has a shipped
        # schema (see CLAUDE.md "Document extraction") - PROCESSING is
        # skipped entirely, not entered-and-no-op'd, for any other type,
        # so a version lands at REVIEW_REQUIRED exactly as it did before
        # this feature existed.
        document = self.documents.get_by_id(organization_id, document_id)
        schema = EXTRACTION_SCHEMAS.get(document.document_type) if document else None

        if schema is None:
            version.status = DocumentVersionStatus.REVIEW_REQUIRED.value
            self.repository.update(version)
            self.db.commit()
            return

        version.status = DocumentVersionStatus.PROCESSING.value
        self.repository.update(version)
        # Committed here, BEFORE the extraction call runs - same crash-
        # visibility precedent as SCANNING itself.
        self.db.commit()

        self._run_extraction(
            version, content, document.document_type,
            organization_id=organization_id, document_id=document_id,
            correlation_id=correlation_id,
        )

    def _run_extraction(
        self,
        version: DocumentVersion,
        content: bytes,
        document_type: str,
        *,
        organization_id: UUID,
        document_id: UUID,
        correlation_id: str | None,
    ) -> None:
        """
        The one place PROCESSING resolves - always to REVIEW_REQUIRED,
        regardless of extraction success or failure (graceful
        degradation: extraction failure must never block anything, the
        document stays fully usable via manual entry). Called from both
        _run_scan_and_transition (the first attempt, right after a clean
        scan) and run_extraction (an explicit on-demand re-run) - so the
        transition logic itself never has to know which caller it's
        serving, same shape as _run_scan_and_transition/retry_scan. See
        CLAUDE.md "Document extraction".
        """
        try:
            # Organization.is_synthetic gate (see CLAUDE.md "Ask
            # RegNova") - checked against the INJECTED extractor's own
            # type, not a settings string - see AssessmentRunService's
            # own identical guard for why. Degrades exactly like any
            # other DocumentExtractionUnavailable reason - no separate
            # path.
            if (
                isinstance(self.extractor, GeminiDocumentExtractor)
                and not require_organization_synthetic(self.db, organization_id)
            ):
                raise DocumentExtractionUnavailable(
                    "organization_not_synthetic",
                    "Organization.is_synthetic is not set - the Gemini free tier "
                    "must only ever see confirmed-synthetic organizations' data.",
                )
            result = self.extractor.extract(
                document_type=document_type, content=content, content_type=version.content_type,
            )
        except DocumentExtractionUnavailable as exc:
            version.status = DocumentVersionStatus.REVIEW_REQUIRED.value
            version.extraction_status = "FAILED"
            version.extraction_error = str(exc)
            self.repository.update(version)
            self.db.commit()
            return

        version.status = DocumentVersionStatus.REVIEW_REQUIRED.value
        version.extraction_status = "COMPLETED"
        version.extraction_error = None
        self.repository.update(version)

        for field in result.fields:
            self.field_service.write_extracted_field(
                organization_id, document_id, version.id, field.field_key,
                value=field.value, confidence=field.confidence,
                ai_model_identifier=result.model_identifier,
                ai_prompt_version=result.schema_version,
                correlation_id=correlation_id,
            )

        # One commit for the whole pass (status + every extracted
        # field), not one per field.
        self.db.commit()

    def run_extraction(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> DocumentVersion:
        """
        On-demand (re-)run - not framed purely as failure-recovery the
        way retry_scan is, since an extraction FAILURE never leaves a
        version stuck (it always already reached REVIEW_REQUIRED).
        Useful beyond retrying a prior failure too - e.g. backfilling
        extraction on an already-uploaded version once a schema ships
        for its type. Valid from REVIEW_REQUIRED (the ordinary case) or
        PROCESSING (a version stuck there from a crashed request -
        operationally the same problem retry_scan solves for SCANNING/
        FAILED) - re-reads the same stored bytes via checksum (content-
        addressed, no new upload). Safe to call repeatedly: writes are
        always new, append-only revisions, never an overwrite.
        """
        version = self.get_by_id(organization_id, document_id, version_id)

        if version.status not in (
            DocumentVersionStatus.REVIEW_REQUIRED.value,
            DocumentVersionStatus.PROCESSING.value,
        ):
            raise DocumentVersionTransitionNotAllowed(
                "Extraction can only be (re-)run while the document version "
                "is REVIEW_REQUIRED or PROCESSING.",
            )

        document = self.documents.get_by_id(organization_id, document_id)
        if EXTRACTION_SCHEMAS.get(document.document_type) is None:
            raise DocumentTypeHasNoExtractionSchema(document.document_type)

        content = self.storage.get(version.checksum)

        self._run_extraction(
            version, content, document.document_type,
            organization_id=organization_id, document_id=document_id,
            correlation_id=correlation_id,
        )

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

        # Fetched BEFORE this call's own revision exists - the field's
        # current (about-to-be-superseded) revision, used only to detect
        # a genuine calibration signal below. None for a brand-new field.
        previous = self.revisions.get_latest(field.id)

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

        payload: dict[str, Any] = {
            "document_id": str(document_id),
            "document_version_id": str(version_id),
            "field_key": field_key,
            "revision_number": next_revision_number,
            "value": value,
            "confidence": confidence,
            "method": "MANUAL",
        }

        # Calibration data collection (see CLAUDE.md "Document
        # extraction" known limitation on confidence calibration): a
        # human overwriting an AI_EXTRACTED value with a MANUAL one is a
        # labelled ground-truth signal - "the model said X at confidence
        # C, a human says the real value is Y" - exactly what's needed
        # to eventually check whether stated confidence tracks actual
        # correctness. Recorded here, on the already-audited
        # DocumentFieldRevised event, not a new table - no calibration
        # ANALYSIS is built from this, only the raw labelled data is
        # captured, for whoever (Regulatory Knowledge Lead, per the
        # named prerequisite) eventually revisits the confidence
        # threshold. Silent (no new payload key at all) for every other
        # transition - MANUAL correcting MANUAL is not an AI signal, and
        # the very first entry for a field has no `previous` at all.
        if previous is not None and previous.method == "AI_EXTRACTED":
            payload["corrected_extraction"] = {
                "previous_value": previous.value,
                "previous_confidence": previous.confidence,
                "ai_model_identifier": previous.ai_model_identifier,
                "ai_prompt_version": previous.ai_prompt_version,
                "values_matched": previous.value == value,
            }

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
            payload=payload,
            correlation_id=correlation_id,
            actor_user_id=actor_user_id,
        )

        self.db.commit()
        self.db.refresh(field)

        return field

    def write_extracted_field(
        self,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        field_key: str,
        *,
        value: str,
        confidence: float,
        ai_model_identifier: str,
        ai_prompt_version: str,
        correlation_id: str | None = None,
    ) -> DocumentField:
        """
        System write path used ONLY by extraction
        (DocumentVersionService._run_extraction), deliberately bypassing
        set_field()'s REVIEW_REQUIRED-only editability gate - extraction
        runs during PROCESSING, before the version has ever reached
        REVIEW_REQUIRED, so that gate simply doesn't apply here and must
        not be widened to accommodate it (set_field()'s own contract for
        human callers stays exactly as it was). entered_by_user_id stays
        null - system-authored, no human decided this, same "engine-
        authored, no actor" precedent as an auto-quarantined
        DocumentVersion's reviewed_by_user_id. Does NOT commit - the
        caller writes several fields from one extraction pass and
        commits once, matching CLAUDE.md "Document extraction"'s
        "one commit per pass" design.
        """
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
            method="AI_EXTRACTED",
            ai_model_identifier=ai_model_identifier,
            ai_prompt_version=ai_prompt_version,
            entered_by_user_id=None,
        )
        self.revisions.create(revision)

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
                "method": "AI_EXTRACTED",
                "ai_model_identifier": ai_model_identifier,
                "ai_prompt_version": ai_prompt_version,
            },
            correlation_id=correlation_id,
            actor_user_id=None,
        )

        return field
