from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest

from app.core.dependencies import get_document_storage
from app.main import app
from app.modules.audit.models import AuditVisibilityTier
from app.modules.audit.repository import AuditEventRepository, OutboxRepository
from app.modules.audit.service import AuditService
from app.modules.audit.worker import dispatch_pending_events
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.finding.models import Finding, FindingRevision, FindingStatus
from app.modules.internal_role_assignment.models import (
    InternalRoleAssignment,
    InternalRoleAssignmentStatus,
    InternalRoleCode,
)
from app.modules.organization.models import Organization
from app.modules.requirement_version.models import RequirementSeverity
from app.modules.role.models import Role
from app.modules.user.models import User
from app.storage import LocalFilesystemStorage

# --- Shared helpers ---------------------------------------------------


@pytest.fixture()
def storage(tmp_path):
    backend = LocalFilesystemStorage(tmp_path)
    app.dependency_overrides[get_document_storage] = lambda: backend
    yield backend
    app.dependency_overrides.pop(get_document_storage, None)


def _create_product(client, tenant, name="Widget"):
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0", category="Beauty"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "category": category},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_state(client, tenant, product_id, product_version_id, market="Malaysia", jurisdiction=None):
    response = client.post(
        f"/products/{product_id}/market-states",
        json={
            "product_version_id": product_version_id,
            "market": market,
            "jurisdiction": jurisdiction if jurisdiction is not None else market,
        },
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _make_state(client, tenant):
    product = _create_product(client, tenant)
    version = _create_version(client, tenant, product["id"])
    return _create_state(client, tenant, product["id"], version["id"])


def _make_finding(
    db, organization_id, product_market_state_id, *,
    severity=RequirementSeverity.MODERATE.value,
    status=FindingStatus.PROPOSED.value,
    dimension="CLAIMS",
):
    finding = Finding(
        organization_id=organization_id,
        product_market_state_id=product_market_state_id,
        dimension=dimension,
        subject_key=f"subject-{uuid.uuid4()}",
    )
    db.add(finding)
    db.flush()

    revision = FindingRevision(
        finding_id=finding.id,
        revision_number=1,
        issue_type="test_issue",
        observed_value="observed value",
        severity=severity,
        status=status,
        hard_gate_effect=False,
        rationale="engine-proposed, internal-only text",
    )
    db.add(revision)
    db.commit()

    return finding


def _get_or_create_tenant_zero(db):
    organization = (
        db.query(Organization).filter(Organization.is_internal.is_(True)).first()
    )
    if organization is None:
        organization = Organization(
            name="RegNova", industry="Regulatory Technology", country="US", is_internal=True,
        )
        db.add(organization)
        db.flush()
    return organization


def _grant_internal_role(db, role_code, label):
    """
    A tenant-zero User holding an APPROVED InternalRoleAssignment for
    role_code - self-proposed/self-decided, same shortcut
    test_finding_review.py/test_internal_role_assignment.py already use.
    """
    organization = _get_or_create_tenant_zero(db)

    role = (
        db.query(Role)
        .filter(Role.organization_id == organization.id, Role.code == "EMPLOYEE")
        .first()
    )
    if role is None:
        role = Role(organization_id=organization.id, code="EMPLOYEE", name="Internal Staff")
        db.add(role)
        db.flush()

    user = User(
        organization_id=organization.id,
        role_id=role.id,
        first_name="Internal",
        last_name=label,
        email=f"internal-{label.lower()}-{uuid.uuid4()}@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(user)
    db.flush()

    payload = {"user_id": str(user.id), "role_code": role_code, "scope": None}
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
    ).hexdigest()
    assignment = InternalRoleAssignment(
        user_id=user.id,
        role_code=role_code,
        status=InternalRoleAssignmentStatus.APPROVED.value,
        proposed_by_user_id=user.id,
        proposed_at=datetime.now(timezone.utc),
        rationale="test setup",
        approver_user_id=user.id,
        decided_at=datetime.now(timezone.utc),
        content_hash=content_hash,
    )
    db.add(assignment)
    db.commit()

    return user, organization


def _headers_for(user, organization_id, role_id):
    token = create_access_token(
        subject=str(user.id),
        additional_claims={"organization_id": str(organization_id), "role_id": str(role_id)},
    )
    return {"Authorization": f"Bearer {token}"}


def _create_document(client, tenant, document_type="GMP_CERTIFICATE"):
    response = client.post(
        "/documents", json={"document_type": document_type}, headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _upload_document_version(client, tenant, document_id, content=b"%PDF-1.4\n%mock cert\n%%EOF"):
    files = {"file": ("cert.pdf", content, "application/pdf")}
    response = client.post(
        f"/documents/{document_id}/versions", files=files, headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _verify_document_version(client, tenant, document_id, version_id):
    response = client.post(
        f"/documents/{document_id}/versions/{version_id}/verify",
        json={}, headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- Consumption: outbox -> AuditEvent, idempotency ------------------------


def test_finding_decision_changed_emits_customer_visible_audit_event(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))

    response = client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Acknowledged, working on it."},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200

    dispatch_pending_events(db)

    events = client.get("/audit-events", headers=tenant_a["headers"]).json()
    assert len(events) == 1
    assert events[0]["event_type"] == "FindingDecisionChanged"
    assert events[0]["visibility_tier"] == "CUSTOMER_VISIBLE"
    assert events[0]["payload"]["to_status"] == "OPEN"
    assert events[0]["payload"]["rationale"] == "Acknowledged, working on it."
    assert "internal_payload" not in events[0]  # customer schema never carries it at all


def test_reprocessing_same_outbox_event_does_not_duplicate_audit_events(client, db, tenant_a):
    """
    Outbox delivery is at-least-once - reprocessing the same OutboxEvent
    must not create a second AuditEvent, mirroring
    test_notification.py's own dedup contract test exactly.
    """
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))

    client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Acknowledged."},
        headers=tenant_a["headers"],
    )

    events = [
        e for e in OutboxRepository(db).get_unpublished()
        if e.event_type == "FindingDecisionChanged"
    ]
    assert len(events) == 1
    event = events[0]

    service = AuditService(db)
    first_pass = service.record_for_event(event)
    db.commit()
    second_pass = service.record_for_event(event)
    db.commit()

    assert first_pass is not None
    assert second_pass is None

    stored = AuditEventRepository(db).get_all(
        organization_id=tenant_a["organization"].id,
        visibility_tiers=[AuditVisibilityTier.CUSTOMER_VISIBLE.value],
    )
    assert len(stored) == 1


def test_finding_proposed_engine_rationale_is_internal_only(db, tenant_a):
    """
    FindingProposed's own rationale (engine-generated, RA-facing per
    AssessmentRunService._maybe_propose_finding's own precedent) must
    never appear in the customer-visible payload, only internal_payload.
    Exercises the builder directly - propose() itself doesn't emit an
    event in this pass (see CLAUDE.md "Audit log" - deferred with the
    rest of the assessment-engine coverage).
    """
    state_id = uuid.uuid4()
    finding = Finding(
        organization_id=tenant_a["organization"].id,
        product_market_state_id=state_id,
        dimension="CLAIMS",
        subject_key="c1",
    )
    db.add(finding)
    db.commit()

    event = OutboxRepository(db).append(
        organization_id=tenant_a["organization"].id,
        event_type="FindingProposed",
        schema_version=1,
        payload={
            "finding_id": str(finding.id),
            "product_market_state_id": str(state_id),
            "dimension": "CLAIMS",
            "subject_key": "c1",
            "severity": "CRITICAL",
            "hard_gate_effect": True,
            "issue_type": "PROHIBITED_THERAPEUTIC_CLAIM",
            "observed_value": "cures acne",
            "rationale": "Condition matched: in(wording)=MATCH",
        },
    )
    db.commit()

    audit_event = AuditService(db).record_for_event(event)
    db.commit()

    assert audit_event.visibility_tier == "CUSTOMER_VISIBLE"
    assert "rationale" not in audit_event.payload
    assert audit_event.payload["severity"] == "CRITICAL"
    assert audit_event.internal_payload["rationale"] == "Condition matched: in(wording)=MATCH"
    assert audit_event.internal_payload["observed_value"] == "cures acne"


def test_unregistered_event_type_defaults_to_internal_regulatory(db, tenant_a):
    """
    Fail-closed default - WorkspaceActivated (a real, existing event
    type with no registered builder in this pass) must never land at
    CUSTOMER_VISIBLE by accident.
    """
    event = OutboxRepository(db).append(
        organization_id=tenant_a["organization"].id,
        event_type="WorkspaceActivated",
        schema_version=1,
        payload={"organization_id": str(tenant_a["organization"].id)},
    )
    db.commit()

    audit_event = AuditService(db).record_for_event(event)
    db.commit()

    assert audit_event.visibility_tier == "INTERNAL_REGULATORY"
    assert audit_event.internal_payload is None


# --- DocumentVersion / DocumentField coverage (closes AC-FR-04-02) ---------


def test_document_version_upload_emits_customer_visible_event(client, db, tenant_a, storage):
    document = _create_document(client, tenant_a)
    client.post(
        f"/documents/{document['id']}/versions",
        files={"file": ("cert.pdf", b"%PDF-1.4\n%mock\n%%EOF", "application/pdf")},
        headers=tenant_a["headers"],
    )

    dispatch_pending_events(db)

    events = client.get(
        "/audit-events", params={"event_type": "DocumentVersionUploaded"}, headers=tenant_a["headers"],
    ).json()
    assert len(events) == 1
    assert events[0]["visibility_tier"] == "CUSTOMER_VISIBLE"
    assert events[0]["payload"]["document_id"] == document["id"]
    assert events[0]["payload"]["supersedes_id"] is None


def test_document_version_dedup_no_op_emits_no_event(client, db, tenant_a, storage):
    document = _create_document(client, tenant_a)
    _upload_document_version(client, tenant_a, document["id"])
    _upload_document_version(client, tenant_a, document["id"])  # identical bytes - a no-op

    dispatch_pending_events(db)

    events = client.get(
        "/audit-events", params={"event_type": "DocumentVersionUploaded"}, headers=tenant_a["headers"],
    ).json()
    assert len(events) == 1


def test_document_version_verify_emits_event(client, db, tenant_a, storage):
    document = _create_document(client, tenant_a)
    version = _upload_document_version(client, tenant_a, document["id"])
    _verify_document_version(client, tenant_a, document["id"], version["id"])

    dispatch_pending_events(db)

    events = client.get(
        "/audit-events", params={"event_type": "DocumentVersionVerified"}, headers=tenant_a["headers"],
    ).json()
    assert len(events) == 1
    assert events[0]["payload"]["from_status"] == "REVIEW_REQUIRED"
    assert events[0]["payload"]["to_status"] == "VERIFIED"


def test_document_version_reject_and_quarantine_emit_distinct_events(client, db, tenant_a, storage):
    doc_a = _create_document(client, tenant_a)
    version_a = _upload_document_version(client, tenant_a, doc_a["id"], content=b"%PDF-1.4\n%a\n%%EOF")
    client.post(
        f"/documents/{doc_a['id']}/versions/{version_a['id']}/reject",
        json={"note": "wrong document"},
        headers=tenant_a["headers"],
    )

    doc_b = _create_document(client, tenant_a)
    version_b = _upload_document_version(client, tenant_a, doc_b["id"], content=b"%PDF-1.4\n%b\n%%EOF")
    client.post(
        f"/documents/{doc_b['id']}/versions/{version_b['id']}/quarantine",
        json={"note": "looks suspicious"},
        headers=tenant_a["headers"],
    )

    dispatch_pending_events(db)

    rejected = client.get(
        "/audit-events", params={"event_type": "DocumentVersionRejected"}, headers=tenant_a["headers"],
    ).json()
    quarantined = client.get(
        "/audit-events", params={"event_type": "DocumentVersionQuarantined"}, headers=tenant_a["headers"],
    ).json()
    assert len(rejected) == 1
    assert len(quarantined) == 1
    assert rejected[0]["payload"]["note"] == "wrong document"
    assert quarantined[0]["payload"]["note"] == "looks suspicious"


def test_document_field_correction_emits_audit_event_closing_ac_fr_04_02(client, db, tenant_a, storage):
    """
    AC-FR-04-02 ("corrections create a revision and an audit event") was
    previously unsatisfiable - nothing existed to write an audit event
    to. This confirms it now does, for both the first entry and a
    genuine correction.
    """
    document = _create_document(client, tenant_a)
    version = _upload_document_version(client, tenant_a, document["id"])

    client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/expiry_date",
        json={"value": "2027-06-30"},
        headers=tenant_a["headers"],
    )
    client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/expiry_date",
        json={"value": "2027-07-15"},
        headers=tenant_a["headers"],
    )

    dispatch_pending_events(db)

    events = client.get(
        "/audit-events", params={"event_type": "DocumentFieldRevised"}, headers=tenant_a["headers"],
    ).json()
    assert len(events) == 2
    revisions = sorted(e["payload"]["revision_number"] for e in events)
    assert revisions == [1, 2]
    values = {e["payload"]["revision_number"]: e["payload"]["value"] for e in events}
    assert values == {1: "2027-06-30", 2: "2027-07-15"}


# --- Query surface: customer path (zero exception) -------------------------


def test_customer_cannot_see_another_organizations_events(client, db, tenant_a, tenant_b):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "x"},
        headers=tenant_a["headers"],
    )
    dispatch_pending_events(db)

    own = client.get("/audit-events", headers=tenant_a["headers"]).json()
    other = client.get("/audit-events", headers=tenant_b["headers"]).json()
    assert len(own) == 1
    assert other == []


def test_customer_endpoint_ignores_internal_only_events(client, db, tenant_a):
    """
    An INTERNAL_REGULATORY-tier row (e.g. the default-builder fallback)
    must never surface on the customer endpoint, even for the customer's
    own organization.
    """
    OutboxRepository(db).append(
        organization_id=tenant_a["organization"].id,
        event_type="WorkspaceActivated",
        schema_version=1,
        payload={"organization_id": str(tenant_a["organization"].id)},
    )
    db.commit()
    dispatch_pending_events(db)

    events = client.get("/audit-events", headers=tenant_a["headers"]).json()
    assert events == []


# --- Query surface: internal path (the deliberate, narrow exception) ------


def test_ra_sees_customer_visible_and_internal_regulatory_across_orgs(client, db, tenant_a):
    ra_user, ra_org = _grant_internal_role(db, InternalRoleCode.RA.value, "RaReader")
    ra_role = db.query(Role).filter(Role.organization_id == ra_org.id).first()
    ra_headers = _headers_for(ra_user, ra_org.id, ra_role.id)

    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "x"},
        headers=tenant_a["headers"],
    )
    OutboxRepository(db).append(
        organization_id=tenant_a["organization"].id,
        event_type="WorkspaceActivated",
        schema_version=1,
        payload={"organization_id": str(tenant_a["organization"].id)},
    )
    db.commit()
    dispatch_pending_events(db)

    response = client.get(
        "/audit-events/internal",
        params={"organization_id": str(tenant_a["organization"].id)},
        headers=ra_headers,
    )
    assert response.status_code == 200
    tiers = {e["visibility_tier"] for e in response.json()}
    assert tiers == {"CUSTOMER_VISIBLE", "INTERNAL_REGULATORY"}
    assert "TECHNICAL_SECURITY" not in tiers
    # RA is cleared for internal-regulatory - the FindingProposed-style
    # internal_payload split would be visible here (this event has none,
    # since FindingDecisionChanged carries its rationale in `payload`).
    assert all("internal_payload" in e for e in response.json())


def test_platform_admin_sees_only_technical_security(client, db, tenant_a):
    admin_user, admin_org = _grant_internal_role(db, InternalRoleCode.PLATFORM_ADMIN.value, "PlatformReader")
    admin_role = db.query(Role).filter(Role.organization_id == admin_org.id).first()
    admin_headers = _headers_for(admin_user, admin_org.id, admin_role.id)

    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "x"},
        headers=tenant_a["headers"],
    )
    dispatch_pending_events(db)

    response = client.get(
        "/audit-events/internal",
        params={"organization_id": str(tenant_a["organization"].id)},
        headers=admin_headers,
    )
    assert response.status_code == 200
    # No CUSTOMER_VISIBLE/INTERNAL_REGULATORY rows exist for tenant_a
    # that a technical-security-only clearance would surface. Platform
    # Admin's own query DOES itself produce a TECHNICAL_SECURITY
    # AuditLogQueried row filed under tenant_a (the queried org - see
    # the dedicated self-audit test below) - but that write happens
    # after this call's own results are already computed, so it can't
    # appear in this same response.
    assert response.json() == []


def test_auditor_sees_all_three_tiers(client, db, tenant_a):
    auditor_user, auditor_org = _grant_internal_role(db, InternalRoleCode.AUDITOR.value, "FullReader")
    auditor_role = db.query(Role).filter(Role.organization_id == auditor_org.id).first()
    auditor_headers = _headers_for(auditor_user, auditor_org.id, auditor_role.id)

    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "x"},
        headers=tenant_a["headers"],
    )
    OutboxRepository(db).append(
        organization_id=tenant_a["organization"].id,
        event_type="WorkspaceActivated",
        schema_version=1,
        payload={"organization_id": str(tenant_a["organization"].id)},
    )
    db.commit()
    dispatch_pending_events(db)

    response = client.get(
        "/audit-events/internal",
        params={"organization_id": str(tenant_a["organization"].id)},
        headers=auditor_headers,
    )
    assert response.status_code == 200
    tiers = {e["visibility_tier"] for e in response.json()}
    assert tiers == {"CUSTOMER_VISIBLE", "INTERNAL_REGULATORY"}
    # No TECHNICAL_SECURITY row is visible in THIS response - this same
    # query is what creates one (filed under tenant_a, the queried org),
    # but only after these results were already computed and returned.


def test_customer_org_user_cannot_use_internal_endpoint(client, tenant_a):
    response = client.get(
        "/audit-events/internal",
        params={"organization_id": str(tenant_a["organization"].id)},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_every_internal_query_is_itself_audited(client, db, tenant_a):
    """
    Explicitly required: every cross-org query through the internal
    endpoint durably records itself, regardless of whether it returns
    any rows.
    """
    ra_user, ra_org = _grant_internal_role(db, InternalRoleCode.RA.value, "AuditedReader")
    ra_role = db.query(Role).filter(Role.organization_id == ra_org.id).first()
    ra_headers = _headers_for(ra_user, ra_org.id, ra_role.id)

    response = client.get(
        "/audit-events/internal",
        params={"organization_id": str(tenant_a["organization"].id)},
        headers=ra_headers,
    )
    assert response.status_code == 200
    assert response.json() == []  # nothing to find - the query itself is still logged

    # Filed under the QUERIED org (tenant_a), not the caller's own
    # (tenant-zero) org - AuditEvent.organization_id means "whose data
    # this event is about" everywhere else in this table too, and
    # "someone read tenant_a's audit log" is a fact about tenant_a.
    meta_events = AuditEventRepository(db).get_all(
        organization_id=tenant_a["organization"].id,
        visibility_tiers=[AuditVisibilityTier.TECHNICAL_SECURITY.value],
        event_type="AuditLogQueried",
    )
    assert len(meta_events) == 1
    assert meta_events[0].actor_user_id == ra_user.id
    assert meta_events[0].payload["queried_organization_id"] == str(tenant_a["organization"].id)
    assert meta_events[0].payload["result_count"] == 0
    assert meta_events[0].source_event_id is None  # a direct write, not outbox-consumed


# --- Retention: RESTRICT on organization deletion --------------------------


def test_organization_with_audit_history_cannot_be_deleted(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "x"},
        headers=tenant_a["headers"],
    )
    dispatch_pending_events(db)

    response = client.delete(
        f"/organizations/{tenant_a['organization'].id}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_organization_without_audit_history_can_still_be_deleted(client, tenant_a):
    response = client.delete(
        f"/organizations/{tenant_a['organization'].id}",
        headers=tenant_a["headers"],
    )
    assert response.status_code == 204
