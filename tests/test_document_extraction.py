from __future__ import annotations

import pytest

from app.core.dependencies import get_document_extractor, get_document_storage
from app.extraction import (
    DocumentExtractionUnavailable,
    DocumentExtractor,
    EXTRACTION_SCHEMAS,
    ExtractedField,
    ExtractionResult,
    GeminiDocumentExtractor,
)
from app.main import app
from app.modules.audit.models import AuditVisibilityTier
from app.modules.audit.repository import AuditEventRepository
from app.modules.audit.worker import dispatch_pending_events
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.role.models import Role
from app.modules.user.models import User
from app.storage import LocalFilesystemStorage

PDF_BYTES = b"%PDF-1.4\n%mock gmp certificate content\n%%EOF"


@pytest.fixture()
def storage(tmp_path):
    backend = LocalFilesystemStorage(tmp_path)
    app.dependency_overrides[get_document_storage] = lambda: backend
    yield backend
    app.dependency_overrides.pop(get_document_storage, None)


class _FakeExtractor(DocumentExtractor):
    """
    A test-controllable DocumentExtractor, installed via
    app.dependency_overrides the same way test_document.py's
    _FakeScanner overrides get_malware_scanner. Tests that don't install
    one get the real dependency resolution (Settings.
    document_extractor_backend defaults to "noop", so NoOpExtractor -
    always an empty result, which is why every pre-existing document
    test needed no changes when extraction was added to the pipeline).
    """

    def __init__(self, fields=None, unavailable_reason=None, model_identifier="fake-vision-1", schema_version="fake-schema-v1"):
        self.fields = fields or []
        self.unavailable_reason = unavailable_reason
        self.model_identifier = model_identifier
        self.schema_version = schema_version
        self.calls = []

    def extract(self, *, document_type, content, content_type):
        self.calls.append((document_type, content_type))
        if self.unavailable_reason:
            raise DocumentExtractionUnavailable(self.unavailable_reason, "simulated")
        return ExtractionResult(
            fields=self.fields, model_identifier=self.model_identifier, schema_version=self.schema_version,
        )


@pytest.fixture()
def extractor_override():
    def _install(extractor):
        app.dependency_overrides[get_document_extractor] = lambda: extractor
        return extractor

    yield _install
    app.dependency_overrides.pop(get_document_extractor, None)


def _employee_headers(db, tenant):
    role = Role(organization_id=tenant["organization"].id, code="EMPLOYEE", name="Employee")
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Rank",
        last_name="File",
        email="employee-extract@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.commit()

    token = create_access_token(
        subject=str(user.id),
        additional_claims={
            "organization_id": str(tenant["organization"].id),
            "role_id": str(role.id),
        },
    )
    return {"Authorization": f"Bearer {token}"}


def _create_document(client, tenant, document_type="GMP_CERTIFICATE"):
    response = client.post(
        "/documents", json={"document_type": document_type}, headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_version(client, tenant, document_id, content=PDF_BYTES, filename="cert.pdf", headers=None):
    files = {"file": (filename, content, "application/pdf")}
    response = client.post(
        f"/documents/{document_id}/versions", files=files, headers=headers or tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_fields(client, tenant, document_id, version_id):
    response = client.get(
        f"/documents/{document_id}/versions/{version_id}/fields", headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_field(client, tenant, document_id, version_id, field_key, value, headers=None):
    response = client.put(
        f"/documents/{document_id}/versions/{version_id}/fields/{field_key}",
        json={"value": value},
        headers=headers or tenant["headers"],
    )
    return response


def _extract(client, tenant, document_id, version_id, headers=None):
    return client.post(
        f"/documents/{document_id}/versions/{version_id}/extract",
        headers=headers or tenant["headers"],
    )


# --- Upload triggers extraction (or doesn't) ----------------------------


def test_upload_with_shipped_schema_runs_extraction_and_writes_fields(client, tenant_a, storage, extractor_override):
    extractor = extractor_override(_FakeExtractor(fields=[
        ExtractedField(field_key="manufacturer", value="Acme Labs", confidence=0.92),
        ExtractedField(field_key="expiry_date", value="2027-03-01", confidence=0.88),
    ]))

    document = _create_document(client, tenant_a, document_type="GMP_CERTIFICATE")
    version = _upload_version(client, tenant_a, document["id"])

    assert version["status"] == "REVIEW_REQUIRED"
    assert version["extraction_status"] == "COMPLETED"
    assert version["extraction_error"] is None
    assert extractor.calls == [("GMP_CERTIFICATE", "application/pdf")]

    fields = _get_fields(client, tenant_a, document["id"], version["id"])
    by_key = {f["field_key"]: f for f in fields}
    assert set(by_key) == {"manufacturer", "expiry_date"}

    manufacturer_rev = by_key["manufacturer"]["revisions"][0]
    assert manufacturer_rev["value"] == "Acme Labs"
    assert manufacturer_rev["confidence"] == 0.92
    assert manufacturer_rev["method"] == "AI_EXTRACTED"
    assert manufacturer_rev["ai_model_identifier"] == "fake-vision-1"
    assert manufacturer_rev["ai_prompt_version"] == "fake-schema-v1"
    assert manufacturer_rev["entered_by_user_id"] is None


def test_upload_extraction_failure_leaves_document_fully_usable_via_manual_entry(
    client, tenant_a, storage, extractor_override,
):
    extractor_override(_FakeExtractor(unavailable_reason="http_error"))

    document = _create_document(client, tenant_a, document_type="GMP_CERTIFICATE")
    version = _upload_version(client, tenant_a, document["id"])

    # Graceful degradation: the version still reaches REVIEW_REQUIRED,
    # never stuck at PROCESSING or diverted to FAILED - extraction
    # failure is not a security gate the way a malware scan failure is.
    assert version["status"] == "REVIEW_REQUIRED"
    assert version["extraction_status"] == "FAILED"
    assert "http_error" in version["extraction_error"]

    # Fully usable via manual entry despite the failure.
    response = _set_field(client, tenant_a, document["id"], version["id"], "manufacturer", "Acme Labs")
    assert response.status_code == 200, response.text
    assert response.json()["revisions"][0]["method"] == "MANUAL"


def test_document_type_without_schema_skips_processing_entirely(client, tenant_a, storage, extractor_override):
    """
    LOA has no shipped extraction schema (see CLAUDE.md "Document
    extraction") - PROCESSING must never even be entered, so the
    extractor is never called at all, not called-and-ignored.
    """
    extractor = extractor_override(_FakeExtractor(fields=[
        ExtractedField(field_key="whatever", value="should never be written", confidence=0.9),
    ]))
    assert "LOA" not in EXTRACTION_SCHEMAS  # the assumption this test depends on

    document = _create_document(client, tenant_a, document_type="LOA")
    version = _upload_version(client, tenant_a, document["id"])

    assert version["status"] == "REVIEW_REQUIRED"
    assert version["extraction_status"] is None
    assert version["extraction_error"] is None
    assert extractor.calls == []

    fields = _get_fields(client, tenant_a, document["id"], version["id"])
    assert fields == []


# --- Calibration data collection (see CLAUDE.md "Document extraction" -----
# "Document extraction confidence calibration is unvalidated") ------------


def test_manual_correction_of_extracted_field_records_calibration_signal(client, db, tenant_a, storage, extractor_override):
    extractor_override(_FakeExtractor(fields=[
        ExtractedField(field_key="manufacturer", value="Acme Labs", confidence=0.4),
    ]))
    document = _create_document(client, tenant_a, document_type="GMP_CERTIFICATE")
    version = _upload_version(client, tenant_a, document["id"])

    response = _set_field(client, tenant_a, document["id"], version["id"], "manufacturer", "Acme Laboratories Inc")
    assert response.status_code == 200, response.text
    assert response.json()["revisions"][-1]["revision_number"] == 2

    dispatch_pending_events(db)
    events = AuditEventRepository(db).get_all(
        organization_id=tenant_a["organization"].id,
        visibility_tiers=[AuditVisibilityTier.CUSTOMER_VISIBLE.value],
        event_type="DocumentFieldRevised",
    )
    corrections = [e for e in events if e.payload.get("revision_number") == 2]
    assert len(corrections) == 1
    corrected = corrections[0].payload["corrected_extraction"]
    assert corrected["previous_value"] == "Acme Labs"
    assert corrected["previous_confidence"] == 0.4
    assert corrected["ai_model_identifier"] == "fake-vision-1"
    assert corrected["ai_prompt_version"] == "fake-schema-v1"
    assert corrected["values_matched"] is False


def test_manual_confirmation_of_extracted_field_records_values_matched_true(client, db, tenant_a, storage, extractor_override):
    extractor_override(_FakeExtractor(fields=[
        ExtractedField(field_key="manufacturer", value="Acme Labs", confidence=0.4),
    ]))
    document = _create_document(client, tenant_a, document_type="GMP_CERTIFICATE")
    version = _upload_version(client, tenant_a, document["id"])

    # A human re-typing the SAME value the model already extracted -
    # still a labelled signal (the model was right), not "no signal".
    response = _set_field(client, tenant_a, document["id"], version["id"], "manufacturer", "Acme Labs")
    assert response.status_code == 200, response.text

    dispatch_pending_events(db)
    events = AuditEventRepository(db).get_all(
        organization_id=tenant_a["organization"].id,
        visibility_tiers=[AuditVisibilityTier.CUSTOMER_VISIBLE.value],
        event_type="DocumentFieldRevised",
    )
    corrected = [e for e in events if e.payload.get("revision_number") == 2][0].payload["corrected_extraction"]
    assert corrected["values_matched"] is True


def test_manual_entry_over_manual_entry_records_no_calibration_signal(client, db, tenant_a, storage, extractor_override):
    """
    Not every second revision is a calibration signal - only one where
    the PRIOR revision was AI_EXTRACTED. A human correcting their own
    earlier manual typo carries no AI ground-truth information.
    """
    extractor_override(_FakeExtractor(fields=[]))  # no extraction for this document
    document = _create_document(client, tenant_a, document_type="GMP_CERTIFICATE")
    version = _upload_version(client, tenant_a, document["id"])

    _set_field(client, tenant_a, document["id"], version["id"], "manufacturer", "Acme Labs")
    _set_field(client, tenant_a, document["id"], version["id"], "manufacturer", "Acme Laboratories Inc")

    dispatch_pending_events(db)
    events = AuditEventRepository(db).get_all(
        organization_id=tenant_a["organization"].id,
        visibility_tiers=[AuditVisibilityTier.CUSTOMER_VISIBLE.value],
        event_type="DocumentFieldRevised",
    )
    second = [e for e in events if e.payload.get("revision_number") == 2][0]
    assert "corrected_extraction" not in second.payload


# --- On-demand re-run (POST .../extract) ---------------------------------


def test_extract_endpoint_reruns_and_appends_new_revision_not_overwrite(client, tenant_a, storage, extractor_override):
    fake = extractor_override(_FakeExtractor(fields=[
        ExtractedField(field_key="manufacturer", value="Acme Labs", confidence=0.5),
    ]))
    document = _create_document(client, tenant_a, document_type="GMP_CERTIFICATE")
    version = _upload_version(client, tenant_a, document["id"])

    fake.fields = [ExtractedField(field_key="manufacturer", value="Acme Laboratories Inc", confidence=0.97)]
    response = _extract(client, tenant_a, document["id"], version["id"])
    assert response.status_code == 200, response.text

    fields = _get_fields(client, tenant_a, document["id"], version["id"])
    manufacturer = next(f for f in fields if f["field_key"] == "manufacturer")
    assert len(manufacturer["revisions"]) == 2
    assert manufacturer["revisions"][0]["value"] == "Acme Labs"
    assert manufacturer["revisions"][1]["value"] == "Acme Laboratories Inc"
    assert manufacturer["revisions"][1]["method"] == "AI_EXTRACTED"


def test_extract_endpoint_requires_manager_tier(client, db, tenant_a, storage, extractor_override):
    extractor_override(_FakeExtractor(fields=[]))
    document = _create_document(client, tenant_a, document_type="GMP_CERTIFICATE")
    version = _upload_version(client, tenant_a, document["id"])

    employee_headers = _employee_headers(db, tenant_a)
    response = _extract(client, tenant_a, document["id"], version["id"], headers=employee_headers)
    assert response.status_code == 403


def test_extract_endpoint_rejects_document_type_without_schema(client, tenant_a, storage, extractor_override):
    extractor_override(_FakeExtractor(fields=[]))
    document = _create_document(client, tenant_a, document_type="LOA")
    version = _upload_version(client, tenant_a, document["id"])

    response = _extract(client, tenant_a, document["id"], version["id"])
    assert response.status_code == 400


# --- GeminiDocumentExtractor unit tests (no network) ---------------------


def test_gemini_extractor_system_instruction_warns_about_embedded_instructions():
    spec = EXTRACTION_SCHEMAS["GMP_CERTIFICATE"]
    instruction = spec.system_instruction.lower()
    assert "never as instructions" in instruction
    assert "manufacturer" in instruction  # the actual field list is present


def test_gemini_extractor_too_large_before_call():
    extractor = GeminiDocumentExtractor(
        api_key="fake-key", model="gemini-3.6-flash", timeout_seconds=5.0,
        synthetic_data_ack=True, max_content_bytes=10,
    )
    with pytest.raises(DocumentExtractionUnavailable) as exc_info:
        extractor.extract(document_type="GMP_CERTIFICATE", content=b"x" * 100, content_type="application/pdf")
    assert exc_info.value.reason == "too_large"


def test_gemini_extractor_unsupported_content_type():
    extractor = GeminiDocumentExtractor(
        api_key="fake-key", model="gemini-3.6-flash", timeout_seconds=5.0,
        synthetic_data_ack=True, max_content_bytes=1_000_000,
    )
    with pytest.raises(DocumentExtractionUnavailable) as exc_info:
        extractor.extract(
            document_type="GMP_CERTIFICATE", content=b"csv,data",
            content_type="text/csv",
        )
    assert exc_info.value.reason == "unsupported_content_type"


def test_gemini_extractor_requires_synthetic_data_ack():
    extractor = GeminiDocumentExtractor(
        api_key="fake-key", model="gemini-3.6-flash", timeout_seconds=5.0,
        synthetic_data_ack=False, max_content_bytes=1_000_000,
    )
    with pytest.raises(DocumentExtractionUnavailable) as exc_info:
        extractor.extract(document_type="GMP_CERTIFICATE", content=PDF_BYTES, content_type="application/pdf")
    assert exc_info.value.reason == "not_configured"


def test_gemini_extractor_parse_response_rejects_extra_key():
    extractor = GeminiDocumentExtractor(
        api_key="fake-key", model="gemini-3.6-flash", timeout_seconds=5.0,
        synthetic_data_ack=True, max_content_bytes=1_000_000,
    )
    spec = EXTRACTION_SCHEMAS["CFS"]
    # A "complied" injection reply tacking on an extra key must be
    # rejected outright, not silently ignored - same exact-key-set
    # discipline as GeminiSemanticAnalyzer._parse_response.
    inner = {f.key: {"value": "", "confidence": 0.0} for f in spec.fields}
    inner["scope"] = "expanded"
    import json as _json
    complied = _json.dumps({
        "candidates": [{"content": {"parts": [{"text": _json.dumps(inner)}]}}],
        "modelVersion": "gemini-test",
    })
    with pytest.raises(DocumentExtractionUnavailable) as exc_info:
        extractor._parse_response(spec, complied)
    assert exc_info.value.reason == "schema_invalid"


def test_gemini_extractor_parse_response_rejects_bad_confidence():
    extractor = GeminiDocumentExtractor(
        api_key="fake-key", model="gemini-3.6-flash", timeout_seconds=5.0,
        synthetic_data_ack=True, max_content_bytes=1_000_000,
    )
    spec = EXTRACTION_SCHEMAS["CFS"]
    inner = {f.key: {"value": "x", "confidence": 1.5} for f in spec.fields}  # out of range
    import json as _json
    body = _json.dumps({
        "candidates": [{"content": {"parts": [{"text": _json.dumps(inner)}]}}],
        "modelVersion": "gemini-test",
    })
    with pytest.raises(DocumentExtractionUnavailable) as exc_info:
        extractor._parse_response(spec, body)
    assert exc_info.value.reason == "schema_invalid"


def test_gemini_extractor_parse_response_skips_empty_values():
    extractor = GeminiDocumentExtractor(
        api_key="fake-key", model="gemini-3.6-flash", timeout_seconds=5.0,
        synthetic_data_ack=True, max_content_bytes=1_000_000,
    )
    spec = EXTRACTION_SCHEMAS["GMP_CERTIFICATE"]
    inner = {f.key: {"value": "", "confidence": 0.0} for f in spec.fields}
    inner["manufacturer"] = {"value": "Acme Labs", "confidence": 0.9}
    import json as _json
    body = _json.dumps({
        "candidates": [{"content": {"parts": [{"text": _json.dumps(inner)}]}}],
        "modelVersion": "gemini-3.6-flash",
    })
    result = extractor._parse_response(spec, body)
    assert [f.field_key for f in result.fields] == ["manufacturer"]
    assert result.model_identifier == "gemini-3.6-flash"
    assert result.schema_version == spec.schema_version
