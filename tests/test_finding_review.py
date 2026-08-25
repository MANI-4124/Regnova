from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.finding.exceptions import (
    FindingTransitionNotAllowed,
    FindingTransitionNotAuthorized,
)
from app.modules.finding.models import Finding, FindingRevision, FindingStatus
from app.modules.finding.service import FindingService
from app.modules.internal_role_assignment.models import (
    InternalRoleAssignment,
    InternalRoleAssignmentStatus,
    InternalRoleCode,
)
from app.modules.organization.models import Organization
from app.modules.requirement_version.models import RequirementSeverity
from app.modules.role.models import Role
from app.modules.user.models import User

# --- Helpers ---------------------------------------------------------


def _create_product(client, tenant, name="Widget"):
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "notes": "initial"},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_state(client, tenant, product_id, product_version_id, market="Malaysia"):
    response = client.post(
        f"/products/{product_id}/market-states",
        json={"product_version_id": product_version_id, "market": market},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
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
    """
    Direct ORM construction, bypassing propose()/the assessment engine -
    these tests are about the transition machinery itself, not
    detection, so there's no need to build a requirement/rule/release
    pipeline just to get a Finding + first revision into a known state.
    """
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
        rationale="engine-proposed",
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
    role_code - self-proposed/self-decided, same "no HR/CEO account
    exists yet in tests" shortcut test_internal_role_assignment.py uses.
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


# --- (1) Full customer-side lifecycle, end to end --------------------


def test_customer_side_lifecycle_end_to_end(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]),
        severity=RequirementSeverity.MODERATE.value,
    )

    accept = client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Acknowledged, working on it."},
        headers=tenant_a["headers"],
    )
    assert accept.status_code == 200
    assert accept.json()["revisions"][-1]["status"] == "OPEN"

    respond = client.post(
        f"/findings/{finding.id}/respond",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Uploaded a corrected COA."},
        headers=tenant_a["headers"],
    )
    assert respond.status_code == 200
    assert respond.json()["revisions"][-1]["status"] == "CUSTOMER_RESPONDED"

    resolve = client.post(
        f"/findings/{finding.id}/resolve",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Verified against the updated COA.", "resolution_decision": "EVIDENCE_ACCEPTED"},
        headers=tenant_a["headers"],
    )
    assert resolve.status_code == 200
    final = resolve.json()

    revisions = final["revisions"]
    assert [r["status"] for r in revisions] == ["PROPOSED", "OPEN", "CUSTOMER_RESPONDED", "RESOLVED"]
    assert revisions[-1]["decided_by_user_id"] == str(tenant_a["user"].id)
    assert revisions[-1]["resolution_decision"] == "EVIDENCE_ACCEPTED"
    # Observation carried forward unchanged across every transition revision.
    assert all(r["observed_value"] == "observed value" for r in revisions)


# --- (2) Illegal transitions rejected ---------------------------------


def test_respond_rejected_when_finding_is_still_proposed(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))

    response = client.post(
        f"/findings/{finding.id}/respond",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "not applicable yet"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FINDING_TRANSITION_NOT_ALLOWED"


def test_accept_rejected_when_finding_already_open(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]), status=FindingStatus.OPEN.value,
    )

    response = client.post(
        f"/findings/{finding.id}/accept",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "already triaged"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 409


def test_reopen_rejected_when_not_customer_responded(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]), status=FindingStatus.OPEN.value,
    )

    ra, _ = _grant_internal_role(db, InternalRoleCode.RA.value, "Reopener")
    service = FindingService(db)

    try:
        service.reopen(
            organization_id=tenant_a["organization"].id,
            product_market_state_id=uuid.UUID(state["id"]),
            finding_id=finding.id,
            actor_user_id=ra.id,
            rationale="nothing to reopen",
        )
        assert False, "expected FindingTransitionNotAllowed"
    except FindingTransitionNotAllowed:
        pass


def test_resolve_rejected_once_already_terminal(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]), status=FindingStatus.RESOLVED.value,
    )

    response = client.post(
        f"/findings/{finding.id}/resolve",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "resolve again?"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 409


# --- (3) Severity gating rejects a customer-side actor ----------------


def test_customer_cannot_resolve_critical_finding(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]),
        severity=RequirementSeverity.CRITICAL.value,
    )

    response = client.post(
        f"/findings/{finding.id}/resolve",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "I fixed it myself"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FINDING_TRANSITION_NOT_AUTHORIZED"


def test_customer_cannot_resolve_major_finding(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]),
        severity=RequirementSeverity.MAJOR.value,
    )

    response = client.post(
        f"/findings/{finding.id}/resolve",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "I fixed it myself"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 403


def test_customer_can_resolve_moderate_finding(client, db, tenant_a):
    """
    The boundary is precise, not "customer always blocked" - only
    Critical/Major require RA/Senior sign-off.
    """
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]),
        severity=RequirementSeverity.MODERATE.value,
    )

    response = client.post(
        f"/findings/{finding.id}/resolve",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "Minor labeling fix applied."},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 200


def test_senior_reviewer_can_resolve_critical_finding_via_service(client, db, tenant_a):
    """
    Proves the RA-only leaf is real, working logic - not just code that
    happens to exist. Called directly against the service (not HTTP):
    an RA/Senior actor can never reach this finding through the router
    at all (their own organization_id is tenant-zero's, never the
    customer's - see test_ra_cannot_reach_finding_via_http_cross_org
    below), but the authorization decision itself is fully exercisable
    and correct independent of that unrelated, separately-deferred
    cross-org access problem.
    """
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]),
        severity=RequirementSeverity.CRITICAL.value,
    )
    senior, _ = _grant_internal_role(db, InternalRoleCode.SENIOR_REVIEWER.value, "Senior")

    service = FindingService(db)
    result = service.resolve(
        organization_id=tenant_a["organization"].id,
        product_market_state_id=uuid.UUID(state["id"]),
        finding_id=finding.id,
        actor_user_id=senior.id,
        rationale="Reviewed and verified against primary source.",
    )
    latest = service.get_revisions(result.id)[-1]
    assert latest.status == FindingStatus.RESOLVED.value
    assert latest.decided_by_user_id == senior.id


def test_ra_alone_cannot_resolve_critical_finding_via_service(client, db, tenant_a):
    """Critical requires Senior Reviewer specifically - ordinary RA
    authority (sufficient for Major) is not enough."""

    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]),
        severity=RequirementSeverity.CRITICAL.value,
    )
    ra, _ = _grant_internal_role(db, InternalRoleCode.RA.value, "OrdinaryRA")

    service = FindingService(db)
    try:
        service.resolve(
            organization_id=tenant_a["organization"].id,
            product_market_state_id=uuid.UUID(state["id"]),
            finding_id=finding.id,
            actor_user_id=ra.id,
            rationale="attempted by ordinary RA",
        )
        assert False, "expected FindingTransitionNotAuthorized"
    except FindingTransitionNotAuthorized:
        pass


def test_ra_can_resolve_major_finding_via_service(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(
        db, tenant_a["organization"].id, uuid.UUID(state["id"]),
        severity=RequirementSeverity.MAJOR.value,
    )
    ra, _ = _grant_internal_role(db, InternalRoleCode.RA.value, "MajorRA")

    service = FindingService(db)
    result = service.resolve(
        organization_id=tenant_a["organization"].id,
        product_market_state_id=uuid.UUID(state["id"]),
        finding_id=finding.id,
        actor_user_id=ra.id,
        rationale="Reviewed and accepted.",
    )
    latest = service.get_revisions(result.id)[-1]
    assert latest.status == FindingStatus.RESOLVED.value


# --- RA-only leaves: customer rejected via HTTP, RA proven via service ---


def test_customer_cannot_reject_finding(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))

    response = client.post(
        f"/findings/{finding.id}/reject",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "I disagree with this finding"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 403


def test_ra_can_reject_finding_via_service(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    ra, _ = _grant_internal_role(db, InternalRoleCode.RA.value, "Rejecter")

    service = FindingService(db)
    result = service.reject(
        organization_id=tenant_a["organization"].id,
        product_market_state_id=uuid.UUID(state["id"]),
        finding_id=finding.id,
        actor_user_id=ra.id,
        rationale="Rule misfired on non-matching wording.",
    )
    latest = service.get_revisions(result.id)[-1]
    assert latest.status == FindingStatus.REJECTED.value


def test_customer_cannot_mark_finding_not_applicable(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))

    response = client.post(
        f"/findings/{finding.id}/mark-not-applicable",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "does not apply to us"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 403


def test_ra_can_mark_finding_not_applicable_via_service(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    ra, _ = _grant_internal_role(db, InternalRoleCode.RA.value, "Applicability")

    service = FindingService(db)
    result = service.mark_not_applicable(
        organization_id=tenant_a["organization"].id,
        product_market_state_id=uuid.UUID(state["id"]),
        finding_id=finding.id,
        actor_user_id=ra.id,
        rationale="Product category excludes this requirement.",
    )
    latest = service.get_revisions(result.id)[-1]
    assert latest.status == FindingStatus.NOT_APPLICABLE.value


def test_customer_cannot_accept_finding_with_rationale(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))

    response = client.post(
        f"/findings/{finding.id}/accept-with-rationale",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "acceptable exception, trust me"},
        headers=tenant_a["headers"],
    )
    assert response.status_code == 403


def test_ra_can_accept_finding_with_rationale_via_service(client, db, tenant_a):
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))
    ra, _ = _grant_internal_role(db, InternalRoleCode.RA.value, "Exception")

    service = FindingService(db)
    result = service.accept_with_rationale(
        organization_id=tenant_a["organization"].id,
        product_market_state_id=uuid.UUID(state["id"]),
        finding_id=finding.id,
        actor_user_id=ra.id,
        rationale="Non-blocking exception, precedent RA-1234.",
    )
    latest = service.get_revisions(result.id)[-1]
    assert latest.status == FindingStatus.ACCEPTED_WITH_RATIONALE.value


# --- Cross-org unreachability, the other half of the actor story ------


def test_ra_cannot_reach_finding_via_http_cross_org(client, db, tenant_a):
    """
    The concrete proof of "real logic, currently unreachable": even
    though FindingService.reject() correctly authorizes an RA actor
    (see test_ra_can_reject_finding_via_service above), the HTTP path
    can never deliver an RA there in the first place - their own JWT
    carries tenant-zero's organization_id, which the org-scoped
    get_by_id lookup can never match against a customer's Finding.
    """
    state = _make_state(client, tenant_a)
    finding = _make_finding(db, tenant_a["organization"].id, uuid.UUID(state["id"]))

    ra, ra_org = _grant_internal_role(db, InternalRoleCode.RA.value, "CrossOrg")
    ra_headers = _headers_for(ra, ra_org.id, ra.role_id)

    response = client.post(
        f"/findings/{finding.id}/reject",
        params={"product_market_state_id": state["id"]},
        json={"rationale": "attempting cross-org access"},
        headers=ra_headers,
    )
    assert response.status_code == 404
