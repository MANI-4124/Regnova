from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.assessment_run.repository import StepRunRepository
from app.modules.audit.models import AuditVisibilityTier
from app.modules.audit.repository import OutboxRepository
from app.modules.audit.service import AUDIT_BUILDERS, AuditService
from app.modules.document.repository import DocumentRepository
from app.modules.document_version.repository import (
    DocumentFieldRepository,
    DocumentFieldRevisionRepository,
    DocumentVersionRepository,
)
from app.modules.evidence.repository import EvidenceRepository
from app.modules.finding.repository import FindingRepository, FindingRevisionRepository
from app.modules.product.repository import ProductRepository
from app.modules.product_market_state.exceptions import ProductMarketStateNotFound
from app.modules.product_market_state.repository import ProductMarketStateRepository
from app.modules.product_version.repository import ProductVersionRepository
from app.modules.regulatory_basis_release.repository import RegulatoryBasisReleaseRepository
from app.modules.requirement_result.repository import RequirementResultRepository
from app.modules.state_snapshot.exceptions import StateSnapshotNotFound
from app.modules.state_snapshot.repository import StateSnapshotRepository
from app.storage import DocumentStorage

from .exceptions import (
    ExportGenerationInvalidType,
    ExportNoSnapshotAvailable,
    ExportNotFound,
    ExportNotReady,
    ExportReaderNotAuthorized,
)
from .models import Export, ExportStatus, ExportType
from .repository import ExportRepository

# Not real legal copy - flagged, not decided. See CLAUDE.md "Exports":
# "not independent truth stores" is the spec's own framing (line 389);
# actual disclaimer wording needs sign-off the same way brand/legal/
# disclaimer copy generally does (spec Appendix: "before high-fidelity
# content freeze").
_DISCLAIMER = (
    "This export reflects RegNova's automated regulatory assessment as recorded "
    "in the system at the stated time. It is not independent legal or regulatory "
    "advice and is not itself an authoritative record - the system's own retained "
    "data is."
)

_FINDINGS_CSV_COLUMNS = [
    "finding_id",
    "dimension",
    "subject_key",
    "severity",
    "hard_gate_effect",
    "status",
    "disposition",
    "requirement_version_id",
    "rule_version_id",
    "assessment_run_id",
    "rationale",
    "created_at",
    "updated_at",
]


@dataclass
class _SyntheticOutboxEvent:
    """
    Just enough shape to satisfy AUDIT_BUILDERS["FindingProposed"]/
    ["FindingDecisionChanged"] - both only ever read `.organization_id`
    and `.payload`. Not a real OutboxEvent, never persisted, never
    dispatched - see CLAUDE.md "Exports" on why this is a LIVE call
    into the builder registry rather than a read of persisted
    AuditEvent rows (the outbox dispatcher isn't scheduled, so a very
    recent Finding change could be missing from the audit table at
    export time; calling the builder directly has no such staleness
    risk).
    """

    organization_id: UUID
    payload: dict[str, Any]


class ExportService:
    """
    Business logic for Export (FR-14's exports half). See CLAUDE.md
    "Exports" for the full design: FINDINGS_CSV is live/customer-facing,
    EVIDENCE_PACK_JSON is snapshot-pinned/internal-only, and both reuse
    the audit builder registry (AUDIT_BUILDERS) for tier/redaction
    rather than re-deriving which Finding fields are customer-safe.
    """

    def __init__(self, db: Session, storage: DocumentStorage):
        self.db = db
        self.storage = storage
        self.repository = ExportRepository(db)
        self.states = ProductMarketStateRepository(db)
        self.snapshots = StateSnapshotRepository(db)
        self.findings = FindingRepository(db)
        self.finding_revisions = FindingRevisionRepository(db)
        self.step_runs = StepRunRepository(db)
        self.requirement_results = RequirementResultRepository(db)
        self.evidence = EvidenceRepository(db)
        self.document_versions = DocumentVersionRepository(db)
        self.documents = DocumentRepository(db)
        self.document_fields = DocumentFieldRepository(db)
        self.document_field_revisions = DocumentFieldRevisionRepository(db)
        self.releases = RegulatoryBasisReleaseRepository(db)
        self.product_versions = ProductVersionRepository(db)
        self.products = ProductRepository(db)
        self.outbox = OutboxRepository(db)
        self.audit = AuditService(db)

    # --- Reads --------------------------------------------------------

    def get_all(self, organization_id: UUID, product_market_state_id: UUID) -> list[Export]:
        return self.repository.get_all(organization_id, product_market_state_id)

    def get_by_id_for_customer(self, organization_id: UUID, export_id: UUID) -> Export:
        export = self.repository.get_by_id_for_org(organization_id, export_id)

        if export is None:
            raise ExportNotFound()

        return export

    # --- Generate: customer path (FINDINGS_CSV only) -------------------

    def generate_findings_csv(
        self,
        organization_id: UUID,
        product_market_state_id: UUID,
        actor_user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> Export:
        state = self.states.get_by_id_only(organization_id, product_market_state_id)
        if state is None:
            raise ProductMarketStateNotFound()

        export = Export(
            organization_id=organization_id,
            export_type=ExportType.FINDINGS_CSV.value,
            product_market_state_id=product_market_state_id,
            status=ExportStatus.GENERATING.value,
            requested_by_user_id=actor_user_id,
        )
        self.repository.create(export)
        self.db.commit()

        try:
            content = self._generate_findings_csv_bytes(organization_id, product_market_state_id)
            self._mark_ready(export, content, "text/csv", correlation_id=correlation_id)
        except Exception as exc:  # noqa: BLE001
            # Same "a run-level failure must still leave a visible,
            # terminal record" reasoning as AssessmentRun - no exception
            # propagates to the caller, the response just carries
            # status=FAILED.
            self._mark_failed(export, str(exc))

        return export

    # --- Generate: internal path (EVIDENCE_PACK_JSON only) -------------

    def generate_evidence_pack(
        self,
        *,
        caller_user_id: UUID,
        organization_id: UUID,
        product_market_state_id: UUID,
        state_snapshot_id: UUID | None,
        correlation_id: str | None = None,
    ) -> Export:
        """
        The second deliberate, narrow exception to "organization_id is
        never client-supplied" - see CLAUDE.md "Deliberate
        organization_id exceptions" for the maintained list. Every call
        self-audits unconditionally, before generation is even
        attempted, so a FAILED generation is still recorded as an
        access attempt - same "the fact that someone asked is what's
        recorded" reasoning as AuditLogQueried.
        """
        granted = self.audit.resolve_internal_tier_grants(caller_user_id)
        if AuditVisibilityTier.INTERNAL_REGULATORY.value not in granted:
            raise ExportReaderNotAuthorized()

        state = self.states.get_by_id_only(organization_id, product_market_state_id)
        if state is None:
            raise ProductMarketStateNotFound()

        if state_snapshot_id is not None:
            snapshot = self.snapshots.get_by_id(
                organization_id, product_market_state_id, state_snapshot_id,
            )
            if snapshot is None:
                raise StateSnapshotNotFound()
        else:
            snapshot = self.snapshots.get_current(product_market_state_id)
            if snapshot is None:
                raise ExportNoSnapshotAvailable()

        export = Export(
            organization_id=organization_id,
            export_type=ExportType.EVIDENCE_PACK_JSON.value,
            product_market_state_id=product_market_state_id,
            state_snapshot_id=snapshot.id,
            status=ExportStatus.GENERATING.value,
            requested_by_user_id=caller_user_id,
        )
        self.repository.create(export)
        self.db.commit()

        self.audit.record_cross_org_access(
            caller_user_id=caller_user_id,
            organization_id=organization_id,
            event_type="EvidencePackAccessed",
            payload={
                "action": "generate",
                "export_id": str(export.id),
                "product_market_state_id": str(product_market_state_id),
                "state_snapshot_id": str(snapshot.id),
            },
            correlation_id=correlation_id,
        )

        try:
            content = self._generate_evidence_pack_bytes(organization_id, state, snapshot)
            self._mark_ready(export, content, "application/json", correlation_id=correlation_id)
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(export, str(exc))

        return export

    # --- Download -------------------------------------------------------

    def resolve_for_download(
        self,
        *,
        caller_user_id: UUID,
        caller_organization_id: UUID,
        export_id: UUID,
        correlation_id: str | None = None,
    ) -> tuple[Export, bytes]:
        """
        One shared endpoint for both export types - which authorization
        branch applies depends on the EXPORT'S OWN export_type, which
        isn't known until the row is loaded (same "the check needs data
        the router can't see yet" shape FindingService's transition
        methods already established). FINDINGS_CSV: caller's own org
        must match. EVIDENCE_PACK_JSON: caller needs INTERNAL_REGULATORY
        clearance, org match not required (inherently cross-org) - and
        every attempt self-audits unconditionally, including one that
        fails downstream (not READY yet), matching AC-FR-14-02's own
        "expired/revoked users cannot download" framing: the FACT of
        the attempt is what's recorded, not just successful downloads.
        """
        export = self.repository.get_by_id_unscoped(export_id)
        if export is None:
            raise ExportNotFound()

        if export.export_type == ExportType.FINDINGS_CSV.value:
            if export.organization_id != caller_organization_id:
                raise ExportNotFound()  # information-hiding, same as every other cross-org 404
        else:
            granted = self.audit.resolve_internal_tier_grants(caller_user_id)
            if AuditVisibilityTier.INTERNAL_REGULATORY.value not in granted:
                raise ExportReaderNotAuthorized()

            self.audit.record_cross_org_access(
                caller_user_id=caller_user_id,
                organization_id=export.organization_id,
                event_type="EvidencePackAccessed",
                payload={
                    "action": "download",
                    "export_id": str(export.id),
                    "product_market_state_id": str(export.product_market_state_id),
                    "state_snapshot_id": (
                        str(export.state_snapshot_id) if export.state_snapshot_id else None
                    ),
                },
                correlation_id=correlation_id,
            )

        if export.status != ExportStatus.READY.value:
            raise ExportNotReady(export.status)

        content = self.storage.get(export.checksum)

        return export, content

    # --- Internals --------------------------------------------------

    def _mark_ready(self, export: Export, content: bytes, content_type: str, *, correlation_id) -> None:
        checksum = hashlib.sha256(content).hexdigest()
        self.storage.put(checksum, content)

        export.status = ExportStatus.READY.value
        export.checksum = checksum
        export.content_type = content_type
        export.size_bytes = len(content)
        export.generated_at = datetime.now(timezone.utc)
        self.repository.update(export)

        self.outbox.append(
            organization_id=export.organization_id,
            event_type="ExportGenerated",
            schema_version=1,
            payload={
                "export_id": str(export.id),
                "export_type": export.export_type,
                "product_market_state_id": str(export.product_market_state_id),
                "state_snapshot_id": (
                    str(export.state_snapshot_id) if export.state_snapshot_id else None
                ),
                "checksum": export.checksum,
                "size_bytes": export.size_bytes,
                "status": export.status,
            },
            actor_user_id=export.requested_by_user_id,
            correlation_id=correlation_id,
        )
        self.db.commit()

    def _mark_failed(self, export: Export, error_message: str) -> None:
        export.status = ExportStatus.FAILED.value
        export.error_message = error_message
        self.repository.update(export)
        self.db.commit()

    def _build_finding_draft(self, finding, revision):
        """
        Reuses AUDIT_BUILDERS directly (a live call, not a read of
        persisted AuditEvent rows) - see _SyntheticOutboxEvent and
        CLAUDE.md "Exports" for why. Which builder applies is decided
        by revision.decided_by_user_id: None means propose()'s own
        engine-authored shape (FindingProposed), set means a human
        transition's shape (FindingDecisionChanged) - the same
        discriminator this codebase's own review workflow already
        establishes for "who wrote this revision".
        """
        if revision.decided_by_user_id is None:
            payload = {
                "finding_id": str(finding.id),
                "product_market_state_id": str(finding.product_market_state_id),
                "dimension": finding.dimension,
                "subject_key": finding.subject_key,
                "assessment_run_id": (
                    str(revision.assessment_run_id) if revision.assessment_run_id else None
                ),
                "requirement_version_id": (
                    str(finding.requirement_version_id) if finding.requirement_version_id else None
                ),
                "rule_version_id": (
                    str(finding.rule_version_id) if finding.rule_version_id else None
                ),
                "severity": revision.severity,
                "hard_gate_effect": revision.hard_gate_effect,
                "issue_type": revision.issue_type,
                "observed_value": revision.observed_value,
                "observed_location": revision.observed_location,
                "rationale": revision.rationale,
            }
            builder = AUDIT_BUILDERS["FindingProposed"]
        else:
            payload = {
                "finding_id": str(finding.id),
                "product_market_state_id": str(finding.product_market_state_id),
                "dimension": finding.dimension,
                # from_status isn't reconstructable from a point-in-time
                # read alone (it belongs to the specific transition call
                # that produced this revision, not the revision row
                # itself) - left null rather than guessed. to_status is
                # simply this revision's own status.
                "from_status": None,
                "to_status": revision.status,
                "rationale": revision.rationale,
                "disposition": revision.disposition,
            }
            builder = AUDIT_BUILDERS["FindingDecisionChanged"]

        event = _SyntheticOutboxEvent(organization_id=finding.organization_id, payload=payload)
        return builder(self.db, event)

    def _generate_findings_csv_bytes(
        self, organization_id: UUID, product_market_state_id: UUID,
    ) -> bytes:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=_FINDINGS_CSV_COLUMNS)
        writer.writeheader()

        for finding in self.findings.get_all(organization_id, product_market_state_id):
            revision = self.finding_revisions.get_latest(finding.id)
            if revision is None:
                continue

            draft = self._build_finding_draft(finding, revision)

            writer.writerow({
                "finding_id": str(finding.id),
                "dimension": finding.dimension,
                "subject_key": finding.subject_key or "",
                "severity": revision.severity,
                "hard_gate_effect": revision.hard_gate_effect,
                "status": revision.status,
                "disposition": revision.disposition or "",
                "requirement_version_id": (
                    str(finding.requirement_version_id) if finding.requirement_version_id else ""
                ),
                "rule_version_id": str(finding.rule_version_id) if finding.rule_version_id else "",
                "assessment_run_id": (
                    str(revision.assessment_run_id) if revision.assessment_run_id else ""
                ),
                # Blank whenever the builder redacted rationale into
                # internal_payload (a still-unreviewed engine proposal) -
                # draft.payload simply has no "rationale" key in that
                # case. This IS the reuse point (3) asked for: no
                # separate redaction rule maintained here.
                "rationale": draft.payload.get("rationale") or "",
                "created_at": finding.created_at.isoformat(),
                "updated_at": revision.created_at.isoformat(),
            })

        return buffer.getvalue().encode("utf-8")

    def _generate_evidence_pack_bytes(self, organization_id: UUID, state, snapshot) -> bytes:
        release = self.releases.get_by_id(state.regulatory_basis_release_id) \
            if state.regulatory_basis_release_id else None
        product_version = (
            self.product_versions.get_by_id(organization_id, state.product_id, state.product_version_id)
            if state.product_version_id else None
        )
        product = self.products.get_by_id(organization_id, state.product_id)

        header = {
            "state_snapshot_id": str(snapshot.id),
            # Explicit per the pack's own header, not just the module
            # docstring - this pack reconstructs the NAMED snapshot,
            # not current live state (unlike the findings CSV, which is
            # deliberately live/unpinned - see CLAUDE.md "Exports").
            "reconstruction_note": (
                "This evidence pack reflects the Product x Market state AS OF "
                "the state_snapshot_id above, not current live data. Findings "
                "below are resolved to the revision current at the snapshot's "
                "own created_at, not today's latest revision."
            ),
            "product_id": str(state.product_id),
            "product_name": product.name if product else None,
            "product_version_id": str(state.product_version_id) if state.product_version_id else None,
            "product_version": product_version.version if product_version else None,
            "category": product_version.category if product_version else None,
            "jurisdiction": state.jurisdiction,
            "market": state.market,
            "regulatory_basis_release_id": (
                str(state.regulatory_basis_release_id) if state.regulatory_basis_release_id else None
            ),
            # Closest existing analog to C1.1's "verification state" -
            # NOT a real approval-verification field. No Approval model
            # exists in this codebase (see "omitted" below); this is
            # StateSnapshot.overall_gate, nothing more.
            "overall_gate": snapshot.overall_gate,
            "raw_progress": float(snapshot.raw_progress),
            "displayed_progress": float(snapshot.displayed_progress),
            "engine_build": snapshot.engine_build,
            "snapshot_created_at": snapshot.created_at.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": _DISCLAIMER,
        }

        regulatory_basis_manifest = None
        if release is not None:
            regulatory_basis_manifest = {
                "release_id": str(release.id),
                "jurisdiction": release.jurisdiction,
                "category": release.category,
                "content_hash": release.content_hash,
                "effective_from": release.effective_from.isoformat() if release.effective_from else None,
                "effective_to": release.effective_to.isoformat() if release.effective_to else None,
                "source_version_ids": [str(i) for i in release.source_version_ids],
                "requirement_version_ids": [str(i) for i in release.requirement_version_ids],
                "rule_version_ids": [str(i) for i in release.rule_version_ids],
            }

        step_runs: list[dict[str, Any]] = []
        requirement_results: list[dict[str, Any]] = []
        if snapshot.assessment_run_id:
            step_runs = [
                {
                    "step_run_id": str(s.id),
                    "dimension": s.dimension,
                    "rule_version_id": str(s.rule_version_id) if s.rule_version_id else None,
                    "subject_key": s.subject_key,
                    "outcome": s.outcome,
                    "unknown_reason": s.unknown_reason,
                    "status": s.status,
                    "trace": s.trace,
                }
                for s in self.step_runs.get_all_for_run(snapshot.assessment_run_id)
            ]
            requirement_results = [
                {
                    "requirement_result_id": str(r.id),
                    "step_run_id": str(r.step_run_id),
                    "requirement_version_id": str(r.requirement_version_id),
                    "rule_version_id": str(r.rule_version_id) if r.rule_version_id else None,
                    "output_type": r.output_type,
                    "outcome": r.outcome,
                    "predicate_inputs": r.predicate_inputs,
                }
                for r in self.requirement_results.get_all_for_run(snapshot.assessment_run_id)
            ]

        findings: list[dict[str, Any]] = []
        for finding in self.findings.get_all(organization_id, state.id):
            revision = self.finding_revisions.get_latest_as_of(finding.id, snapshot.created_at)
            if revision is None:
                continue  # didn't exist yet as of this snapshot

            draft = self._build_finding_draft(finding, revision)
            entry = dict(draft.payload)
            if draft.internal_payload:
                entry.update(draft.internal_payload)
            entry["finding_id"] = str(finding.id)
            entry["revision_number"] = revision.revision_number
            entry["as_of_revision_created_at"] = revision.created_at.isoformat()
            findings.append(entry)

        evidence_entries: list[dict[str, Any]] = []
        for evidence in self.evidence.get_all(organization_id, state.product_id):
            document_version = self.document_versions.get_by_id_for_org(
                organization_id, evidence.document_version_id,
            )
            document = (
                self.documents.get_by_id(organization_id, document_version.document_id)
                if document_version else None
            )

            fields: dict[str, Any] = {}
            if document_version is not None:
                for field in self.document_fields.get_all_for_version(document_version.id):
                    latest = self.document_field_revisions.get_latest(field.id)
                    if latest is not None:
                        fields[field.field_key] = {"value": latest.value, "confidence": latest.confidence}

            evidence_entries.append({
                "evidence_id": str(evidence.id),
                "document_version_id": str(evidence.document_version_id),
                "document_type": document.document_type if document else None,
                "status": document_version.status if document_version else None,
                "checksum": document_version.checksum if document_version else None,
                "requirement_version_id": (
                    str(evidence.requirement_version_id) if evidence.requirement_version_id else None
                ),
                "is_current": evidence.is_current,
                "fields": fields,
                # Named gap, not fixed here - see CLAUDE.md "Exports":
                # no endpoint anywhere in this codebase serves a
                # DocumentVersion's raw binary, only metadata. This
                # pack can reference the document version; it cannot
                # hand back the file.
                "file_download": None,
            })

        pack = {
            "header": header,
            "regulatory_basis": regulatory_basis_manifest,
            "dimension_summary": snapshot.dimension_summary,
            "step_runs": step_runs,
            "requirement_results": requirement_results,
            "findings": findings,
            "evidence": evidence_entries,
            # Explicit per the user-story wish list ("models, prompts,
            # approvals") this pass structurally cannot satisfy - named,
            # not silently glossed over.
            "omitted": {
                "models_prompts_parsers": "No AI/model layer exists in this codebase.",
                "approvals": "No Approval model exists in this codebase.",
            },
        }

        return json.dumps(pack, indent=2, sort_keys=True, default=str).encode("utf-8")
