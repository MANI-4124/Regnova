from __future__ import annotations

from app.modules.assessment_run.service import AssessmentRunService
from app.modules.requirement_result.repository import RequirementResultRepository

# --- Synthetic Label fixtures only - never real seeded NPRA content ---


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


def _create_requirement_version(client, tenant, **overrides):
    requirement = client.post("/requirements", json={}, headers=tenant["headers"]).json()

    payload = {
        "jurisdiction": "Malaysia",
        "market": "Malaysia",
        "authority": "NPRA",
        "category": "Label",
        "dimension": "LABEL",
        "obligation_type": "MANDATORY_NET_QUANTITY_DECLARATION",
        "canonical_statement": "Net quantity must be declared and legible on the primary panel.",
        "default_severity": "MAJOR",
        "is_hard_gate": True,
        "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
    }
    payload.update(overrides)

    response = client.post(
        f"/requirements/{requirement['id']}/versions",
        json=payload,
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return requirement, response.json()


def _activate_requirement_version(client, tenant, requirement, version):
    response = client.put(
        f"/requirements/{requirement['id']}/versions/{version['id']}",
        json={"status": "ACTIVE", "verified_at": "2026-01-01T00:00:00Z"},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_rule_version(client, tenant, requirement_version_id, **overrides):
    rule = client.post("/rules", json={}, headers=tenant["headers"]).json()

    payload = {
        "requirement_version_id": requirement_version_id,
        "condition": {"op": "not_exists", "field": "extracted"},
        "output_type": "FINDING_PROPOSAL",
        "unknown_behavior": "HUMAN_REVIEW",
    }
    payload.update(overrides)

    response = client.post(
        f"/rules/{rule['id']}/versions",
        json=payload,
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return rule, response.json()


def _activate_rule_version(client, tenant, rule, version):
    response = client.put(
        f"/rules/{rule['id']}/versions/{version['id']}",
        json={"status": "ACTIVE", "verified_at": "2026-01-01T00:00:00Z"},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _create_active_release(client, tenant, rule_version_ids, requirement_version_ids):
    source = client.post("/sources", headers=tenant["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Test Source",
            "issuing_authority": "Test Authority",
            "jurisdiction": "Malaysia",
            "tier": 1,
            "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=tenant["headers"],
    ).json()
    activated_source = client.put(
        f"/sources/{source['id']}/versions/{source_version['id']}",
        json={"status": "ACTIVE", "verified_at": "2026-01-01T00:00:00Z"},
        headers=tenant["headers"],
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
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _build_label_rule(
    client,
    tenant,
    *,
    condition,
    output_type="FINDING_PROPOSAL",
    unknown_behavior="HUMAN_REVIEW",
    default_severity="MAJOR",
    **requirement_overrides,
):
    requirement, requirement_version = _create_requirement_version(
        client, tenant, default_severity=default_severity, **requirement_overrides,
    )
    requirement_version = _activate_requirement_version(client, tenant, requirement, requirement_version)

    rule, rule_version = _create_rule_version(
        client,
        tenant,
        requirement_version["id"],
        condition=condition,
        output_type=output_type,
        unknown_behavior=unknown_behavior,
    )
    rule_version = _activate_rule_version(client, tenant, rule, rule_version)

    release = _create_active_release(
        client, tenant,
        rule_version_ids=[rule_version["id"]],
        requirement_version_ids=[requirement_version["id"]],
    )

    return requirement_version, rule_version, release


def _run_assessment(client, tenant, state_id, label_fields, product_facts=None):
    response = client.post(
        "/assessment-runs",
        json={
            "product_market_state_id": state_id,
            "dimensions": ["LABEL"],
            "input_facts": {
                "LABEL": {
                    "product": product_facts or {},
                    "label_fields": label_fields,
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


def _net_quantity_field(value="50 mL", confidence=0.95, location=None):
    return {
        "field_key": "net_quantity",
        "value": value,
        "confidence": confidence,
        "location": location or {"page": 2, "region": [120, 340, 460, 380]},
    }


# --- Tests -------------------------------------------------------------


def test_label_missing_mandatory_field_proposes_finding(client, tenant_a):
    _build_label_rule(
        client, tenant_a,
        condition={"op": "not_exists", "field": "extracted"},
        output_type="FINDING_PROPOSAL",
        unknown_behavior="HUMAN_REVIEW",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    # No net_quantity field extracted at all - "extracted" key absent.
    run = _run_assessment(
        client, tenant_a, state["id"],
        label_fields=[{"field_key": "net_quantity", "value": None, "confidence": 0.0}],
    )
    assert run["status"] == "COMPLETED"

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    step = detail["step_runs"][0]
    assert step["subject_key"] == "net_quantity"

    # Direct assertion, not just the downstream Finding side effect:
    # not_exists must resolve MATCH because "extracted" was omitted for
    # the null value - if it had been wrapped as {"value": None,
    # "confidence": 0.0} instead, "extracted" would structurally exist
    # and this would be NO_MATCH (no finding proposed at all).
    assert step["outcome"] == "MATCH"
    assert "extracted" not in step["input_facts"]

    findings = _get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1
    assert findings[0]["subject_key"] == "net_quantity"


def test_clean_high_confidence_label_field_is_compliant(client, tenant_a):
    _build_label_rule(
        client, tenant_a,
        condition={"op": "not_exists", "field": "extracted"},
        output_type="FINDING_PROPOSAL",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        label_fields=[_net_quantity_field(value="50 mL", confidence=0.95)],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["dimension_assessments"][0]["state"] == "COMPLIANT"
    assert _get_findings(client, tenant_a, state["id"]) == []


def test_low_confidence_overrides_fail_closed_requirement_result(client, tenant_a):
    """
    The core AC-FR-06-02 guarantee: a rule author declaring FAIL_CLOSED
    for missing-data cases must NOT get to silently force a definite
    (NOT_SATISFIED) outcome when the real problem is untrustworthy OCR -
    that must escalate to human review regardless of the rule's own
    declared policy.
    """

    _build_label_rule(
        client, tenant_a,
        condition={"op": "equals", "field": "extracted", "value": "50 mL"},
        output_type="REQUIREMENT_RESULT",
        unknown_behavior="FAIL_CLOSED",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        label_fields=[_net_quantity_field(value="50 mL", confidence=0.31)],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    step = detail["step_runs"][0]
    assert step["outcome"] == "UNKNOWN"
    assert step["trace"][0]["reason"] == "low_confidence"

    # Not NON_COMPLIANT (which FAIL_CLOSED would normally force via
    # NOT_SATISFIED) - the confidence override wins.
    assert detail["dimension_assessments"][0]["state"] == "HUMAN_REVIEW_REQUIRED"


def test_low_confidence_overrides_request_input_requirement_result(client, tenant_a):
    _build_label_rule(
        client, tenant_a,
        condition={"op": "equals", "field": "extracted", "value": "50 mL"},
        output_type="REQUIREMENT_RESULT",
        unknown_behavior="REQUEST_INPUT",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        label_fields=[_net_quantity_field(value="50 mL", confidence=0.2)],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    # Not PENDING_INPUT (which REQUEST_INPUT would normally produce) -
    # the confidence override wins.
    assert detail["dimension_assessments"][0]["state"] == "HUMAN_REVIEW_REQUIRED"


def test_low_confidence_still_proposes_finding_despite_request_input(client, tenant_a):
    """
    For a merely-missing field, REQUEST_INPUT suppresses the Finding
    entirely (see test_assessment_run_claims.py). Low confidence must
    NOT get the same pass - AC-FR-06-02 requires it becomes Human Review
    Required, and a FINDING_PROPOSAL rule still proposes a finding
    (with a rationale explaining the override), not silently skip it.
    """

    _build_label_rule(
        client, tenant_a,
        condition={"op": "equals", "field": "extracted", "value": "50 mL"},
        output_type="FINDING_PROPOSAL",
        unknown_behavior="REQUEST_INPUT",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        label_fields=[_net_quantity_field(value="50 mL", confidence=0.1)],
    )
    assert run["status"] == "COMPLETED"

    findings = _get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1

    finding_detail = client.get(
        f"/findings/{findings[0]['id']}",
        params={"product_market_state_id": state["id"]},
        headers=tenant_a["headers"],
    ).json()
    rationale = finding_detail["revisions"][0]["rationale"]
    assert "AC-FR-06-02" in rationale
    assert "REQUEST_INPUT" in rationale


def test_finding_observed_location_populated_from_label_field(client, tenant_a):
    _build_label_rule(
        client, tenant_a,
        condition={"op": "not_exists", "field": "extracted"},
        output_type="FINDING_PROPOSAL",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    location = {"page": 3, "region": [1, 2, 3, 4]}
    run = _run_assessment(
        client, tenant_a, state["id"],
        label_fields=[{"field_key": "net_quantity", "value": None, "confidence": 0.0, "location": location}],
    )
    assert run["status"] == "COMPLETED"

    findings = _get_findings(client, tenant_a, state["id"])
    finding_detail = client.get(
        f"/findings/{findings[0]['id']}",
        params={"product_market_state_id": state["id"]},
        headers=tenant_a["headers"],
    ).json()
    assert finding_detail["revisions"][0]["observed_location"] == location


def test_requirement_result_predicate_inputs_include_extracted_confidence(client, tenant_a, db):
    _build_label_rule(
        client, tenant_a,
        condition={"op": "equals", "field": "extracted", "value": "50 mL"},
        output_type="REQUIREMENT_RESULT",
        unknown_behavior="FAIL_CLOSED",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    _run_assessment(
        client, tenant_a, state["id"],
        label_fields=[_net_quantity_field(value="50 mL", confidence=0.95)],
    )

    repo = RequirementResultRepository(db)
    results = repo.get_all()
    assert len(results) == 1
    assert results[0].outcome == "SATISFIED"
    assert results[0].predicate_inputs["extracted"]["confidence"] == 0.95


def test_build_label_field_facts_omits_extracted_key_for_null_value(db):
    """
    Unit-level test directly on the fix site: a null value must not
    become a null-valued {"value": None, "confidence": ...} wrapper,
    which would make the field structurally "exist" and make
    not_exists/missing-field handling unreachable for exactly the case
    Label needs it most (a mandatory field extraction found nothing for).
    """

    service = AssessmentRunService(db)

    facts = service._build_label_field_facts(
        {"field_key": "net_quantity", "value": None, "confidence": 0.0, "location": None},
    )
    assert "extracted" not in facts
    assert facts["field_key"] == "net_quantity"


def test_build_label_field_facts_keeps_extracted_key_for_present_value(db):
    service = AssessmentRunService(db)

    facts = service._build_label_field_facts(
        {"field_key": "net_quantity", "value": "50 mL", "confidence": 0.92, "location": None},
    )
    assert facts["extracted"] == {"value": "50 mL", "confidence": 0.92}
