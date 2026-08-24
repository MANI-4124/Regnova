from __future__ import annotations

import uuid

from app.engine import evaluate_condition
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.requirement_result.exceptions import InvalidRequirementResultOutcome
from app.modules.requirement_result.repository import RequirementResultRepository
from app.modules.role.models import Role
from app.modules.user.models import User

# --- Synthetic Claims fixtures only - never real seeded NPRA content ---

PROHIBITED_WORDINGS = ["Cures Acne", "Treats Eczema"]


def _manager_headers(db, tenant):
    role = Role(organization_id=tenant["organization"].id, code="MANAGER", name="Manager")
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Man",
        last_name="Ager",
        email="manager-ar@example.com",
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


def _create_product(client, tenant, name="Widget"):
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version},
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


def _create_requirement_version(client, writer, **overrides):
    requirement = client.post("/requirements", json={}, headers=writer["headers"]).json()

    payload = {
        "jurisdiction": "Malaysia",
        "market": "Malaysia",
        "authority": "NPRA",
        "category": "Claims",
        "dimension": "CLAIMS",
        "obligation_type": "PROHIBITED_THERAPEUTIC_CLAIM",
        "canonical_statement": "Cosmetic claims must not imply a therapeutic/medical effect.",
        "default_severity": "CRITICAL",
        "is_hard_gate": True,
        "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
    }
    payload.update(overrides)

    response = client.post(
        f"/requirements/{requirement['id']}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return requirement, response.json()


def _activate_requirement_version(client, writer, requirement, version):
    response = client.put(
        f"/requirements/{requirement['id']}/versions/{version['id']}",
        json={"status": "ACTIVE", "verified_at": "2026-01-01T00:00:00Z"},
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_rule_version(client, writer, requirement_version_id, **overrides):
    rule = client.post("/rules", json={}, headers=writer["headers"]).json()

    payload = {
        "requirement_version_id": requirement_version_id,
        "condition": {"op": "in", "field": "wording", "value": PROHIBITED_WORDINGS},
        "output_type": "FINDING_PROPOSAL",
        "unknown_behavior": "HUMAN_REVIEW",
    }
    payload.update(overrides)

    response = client.post(
        f"/rules/{rule['id']}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return rule, response.json()


def _activate_rule_version(client, writer, rule, version):
    response = client.put(
        f"/rules/{rule['id']}/versions/{version['id']}",
        json={"status": "ACTIVE", "verified_at": "2026-01-01T00:00:00Z"},
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_active_release(client, writer, rule_version_ids, requirement_version_ids):
    source = client.post("/sources", headers=writer["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Test Source",
            "issuing_authority": "Test Authority",
            "jurisdiction": "Malaysia",
            "tier": 1,
            "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=writer["headers"],
    ).json()
    activated_source = client.put(
        f"/sources/{source['id']}/versions/{source_version['id']}",
        json={"status": "ACTIVE", "verified_at": "2026-01-01T00:00:00Z"},
        headers=writer["headers"],
    ).json()

    response = client.post(
        "/regulatory-basis-releases",
        json={
            "jurisdiction": "Malaysia",
            "market": "Malaysia",
            "source_version_ids": [activated_source["id"]],
            "requirement_version_ids": requirement_version_ids,
            "rule_version_ids": rule_version_ids,
        },
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _build_claims_rule(
    client,
    writer,
    *,
    condition,
    output_type="FINDING_PROPOSAL",
    unknown_behavior="HUMAN_REVIEW",
    default_severity="CRITICAL",
    **requirement_overrides,
):
    """
    Full pipeline: eligible RequirementVersion + RuleVersion, both
    ACTIVE+verified, included in a fresh active release. Returns
    (requirement_version, rule_version, release).
    """

    requirement, requirement_version = _create_requirement_version(
        client, writer, default_severity=default_severity, **requirement_overrides,
    )
    requirement_version = _activate_requirement_version(client, writer, requirement, requirement_version)

    rule, rule_version = _create_rule_version(
        client,
        writer,
        requirement_version["id"],
        condition=condition,
        output_type=output_type,
        unknown_behavior=unknown_behavior,
    )
    rule_version = _activate_rule_version(client, writer, rule, rule_version)

    release = _create_active_release(
        client, writer,
        rule_version_ids=[rule_version["id"]],
        requirement_version_ids=[requirement_version["id"]],
    )

    return requirement_version, rule_version, release


def _run_assessment(client, tenant, state_id, claims, product_facts=None):
    response = client.post(
        "/assessment-runs",
        json={
            "product_market_state_id": state_id,
            "dimensions": ["CLAIMS"],
            "input_facts": {
                "CLAIMS": {
                    "product": product_facts or {},
                    "claims": claims,
                },
            },
        },
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _get_run_detail(client, tenant, state_id, run_id):
    response = client.get(
        f"/assessment-runs/{run_id}",
        params={"product_market_state_id": state_id},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _get_findings(client, tenant, state_id):
    response = client.get(
        "/findings",
        params={"product_market_state_id": state_id},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


# --- Tests -------------------------------------------------------------


def test_finding_proposal_on_match_marks_dimension_non_compliant(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "in", "field": "wording", "value": PROHIBITED_WORDINGS},
        output_type="FINDING_PROPOSAL",
        unknown_behavior="HUMAN_REVIEW",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])
    assert state["regulatory_basis_release_id"] is not None

    run = _run_assessment(
        client, tenant_a, state["id"],
        claims=[{"claim_id": "clm_1", "wording": "Cures Acne"}],
    )
    assert run["status"] == "COMPLETED"

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert len(detail["dimension_assessments"]) == 1
    assert detail["dimension_assessments"][0]["state"] == "NON_COMPLIANT"

    step = detail["step_runs"][0]
    assert step["outcome"] == "MATCH"
    assert step["trace"]
    assert step["input_hash"]

    findings = _get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1
    assert findings[0]["subject_key"] == "clm_1"

    finding_detail = client.get(
        f"/findings/{findings[0]['id']}",
        params={"product_market_state_id": state["id"]},
        headers=tenant_a["headers"],
    ).json()
    assert finding_detail["revisions"][0]["status"] == "PROPOSED"
    assert finding_detail["revisions"][0]["severity"] == "CRITICAL"
    assert "Condition matched" in finding_detail["revisions"][0]["rationale"]


def test_clean_claim_produces_no_finding_and_compliant_dimension(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "in", "field": "wording", "value": PROHIBITED_WORDINGS},
        output_type="FINDING_PROPOSAL",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        claims=[{"claim_id": "clm_1", "wording": "Softens skin"}],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["dimension_assessments"][0]["state"] == "COMPLIANT"
    assert _get_findings(client, tenant_a, state["id"]) == []


def test_fail_closed_missing_input_proposes_finding_anyway(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "substantiation_status", "value": "expired"},
        output_type="FINDING_PROPOSAL",
        unknown_behavior="FAIL_CLOSED",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        claims=[{"claim_id": "clm_1", "wording": "Reduces wrinkles"}],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["step_runs"][0]["outcome"] == "UNKNOWN"
    assert detail["dimension_assessments"][0]["state"] == "NON_COMPLIANT"

    findings = _get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1
    finding_detail = client.get(
        f"/findings/{findings[0]['id']}",
        params={"product_market_state_id": state["id"]},
        headers=tenant_a["headers"],
    ).json()
    assert "fail-closed" in finding_detail["revisions"][0]["rationale"]


def test_request_input_missing_creates_no_finding_and_pending_input(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "substantiation_status", "value": "expired"},
        output_type="FINDING_PROPOSAL",
        unknown_behavior="REQUEST_INPUT",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        claims=[{"claim_id": "clm_1", "wording": "Reduces wrinkles"}],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["dimension_assessments"][0]["state"] == "PENDING_INPUT"
    assert _get_findings(client, tenant_a, state["id"]) == []


def test_human_review_missing_input_marks_requirement_result_dimension_human_review(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "substantiation_status", "value": "current"},
        output_type="REQUIREMENT_RESULT",
        unknown_behavior="HUMAN_REVIEW",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        claims=[{"claim_id": "clm_1", "wording": "Reduces wrinkles"}],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["dimension_assessments"][0]["state"] == "HUMAN_REVIEW_REQUIRED"
    assert _get_findings(client, tenant_a, state["id"]) == []


def test_fail_closed_requirement_result_missing_input_marks_non_compliant(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "substantiation_status", "value": "current"},
        output_type="REQUIREMENT_RESULT",
        unknown_behavior="FAIL_CLOSED",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        claims=[{"claim_id": "clm_1", "wording": "Reduces wrinkles"}],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["dimension_assessments"][0]["state"] == "NON_COMPLIANT"


def test_applicability_does_not_apply_marks_dimension_not_applicable(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "product.category_id", "value": "drug"},
        output_type="APPLICABILITY",
        unknown_behavior="HUMAN_REVIEW",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        claims=[{"claim_id": "clm_1", "wording": "Softens skin"}],
        product_facts={"category_id": "cosmetic"},
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["dimension_assessments"][0]["state"] == "NOT_APPLICABLE"


def test_rerun_reuses_same_finding_with_incrementing_revision(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "in", "field": "wording", "value": PROHIBITED_WORDINGS},
        output_type="FINDING_PROPOSAL",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])
    claims = [{"claim_id": "clm_1", "wording": "Cures Acne"}]

    _run_assessment(client, tenant_a, state["id"], claims=claims)
    first_findings = _get_findings(client, tenant_a, state["id"])
    assert len(first_findings) == 1

    _run_assessment(client, tenant_a, state["id"], claims=claims)
    second_findings = _get_findings(client, tenant_a, state["id"])

    assert len(second_findings) == 1
    assert second_findings[0]["id"] == first_findings[0]["id"]

    finding_detail = client.get(
        f"/findings/{first_findings[0]['id']}",
        params={"product_market_state_id": state["id"]},
        headers=tenant_a["headers"],
    ).json()
    assert [r["revision_number"] for r in finding_detail["revisions"]] == [1, 2]


def test_create_assessment_run_without_active_release_returns_409(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"], market="Freedonia")
    assert state["regulatory_basis_release_id"] is None

    response = client.post(
        "/assessment-runs",
        json={
            "product_market_state_id": state["id"],
            "dimensions": ["CLAIMS"],
            "input_facts": {"CLAIMS": {"claims": []}},
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 409


def test_create_assessment_run_unsupported_dimension_returns_400(client, tenant_a, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "exists", "field": "wording"},
        output_type="FINDING_PROPOSAL",
    )
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    response = client.post(
        "/assessment-runs",
        json={
            "product_market_state_id": state["id"],
            "dimensions": ["INGREDIENTS"],
            "input_facts": {},
        },
        headers=tenant_a["headers"],
    )
    assert response.status_code == 400


def test_assessment_runs_are_isolated_across_organizations(client, tenant_a, tenant_b, regulatory_content_writer):
    _build_claims_rule(
        client, regulatory_content_writer,
        condition={"op": "exists", "field": "wording"},
        output_type="FINDING_PROPOSAL",
    )
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])
    run = _run_assessment(client, tenant_a, state["id"], claims=[{"claim_id": "clm_1", "wording": "x"}])

    response = client.get(
        f"/assessment-runs/{run['id']}",
        params={"product_market_state_id": state["id"]},
        headers=tenant_b["headers"],
    )
    assert response.status_code == 404

    findings_response = client.get(
        "/findings",
        params={"product_market_state_id": state["id"]},
        headers=tenant_b["headers"],
    )
    assert findings_response.status_code == 404


def test_create_assessment_run_rejects_non_admin(client, db, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"], market="Freedonia")

    headers = _manager_headers(db, tenant_a)
    response = client.post(
        "/assessment-runs",
        json={
            "product_market_state_id": state["id"],
            "dimensions": ["CLAIMS"],
            "input_facts": {"CLAIMS": {"claims": []}},
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_requirement_result_rejects_outcome_outside_closed_vocabulary(db):
    repo = RequirementResultRepository(db)

    try:
        repo.create_validated(
            step_run_id=uuid.uuid4(),
            assessment_run_id=uuid.uuid4(),
            requirement_version_id=uuid.uuid4(),
            rule_version_id=None,
            output_type="APPLICABILITY",
            outcome="SATISFIED",  # valid for REQUIREMENT_RESULT, not APPLICABILITY
            predicate_inputs={},
        )
        assert False, "expected InvalidRequirementResultOutcome"
    except InvalidRequirementResultOutcome:
        pass


def test_engine_validated_against_real_persisted_rule_version_test_fixtures(client, tenant_a, regulatory_content_writer):
    """
    Creates a real RuleVersion via the API with test_fixtures populated
    (synthetic Claims data), fetches it back, and validates the engine
    against RuleVersion.test_fixtures as a persisted field - not just a
    local dict shaped like it.
    """

    requirement, requirement_version = _create_requirement_version(client, regulatory_content_writer)
    requirement_version = _activate_requirement_version(client, regulatory_content_writer, requirement, requirement_version)

    condition = {
        "op": "in",
        "field": "normalized_wording",
        "value": ["cures acne", "treats eczema"],
        "normalize": "lowercase",
    }
    test_fixtures = [
        {"input_facts": {"normalized_wording": "Cures Acne"}, "expected_output": "MATCH"},
        {"input_facts": {"normalized_wording": "soothes dry skin"}, "expected_output": "NO_MATCH"},
        {"input_facts": {}, "expected_output": "UNKNOWN"},
    ]

    rule, rule_version = _create_rule_version(
        client, regulatory_content_writer, requirement_version["id"],
        condition=condition,
        output_type="FINDING_PROPOSAL",
        test_fixtures=test_fixtures,
    )

    fetched = client.get(
        f"/rules/{rule['id']}/versions/{rule_version['id']}",
        headers=tenant_a["headers"],
    ).json()

    assert fetched["test_fixtures"] == test_fixtures

    for fixture in fetched["test_fixtures"]:
        result = evaluate_condition(fetched["condition"], fixture["input_facts"])
        assert result.outcome == fixture["expected_output"], fixture
