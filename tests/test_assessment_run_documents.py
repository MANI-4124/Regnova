from __future__ import annotations

from datetime import datetime, timezone

from app.modules.assessment_run.service import AssessmentRunService

# --- Synthetic Documents fixtures only - never real seeded NPRA content ---


def _create_product(client, tenant, name="Widget"):
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0", category="Documents"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "category": category},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
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
    assert response.status_code == 200
    return response.json()


def _create_requirement_version(client, writer, **overrides):
    requirement = client.post("/requirements", json={}, headers=writer["headers"]).json()

    payload = {
        "jurisdiction": "Malaysia",
        "market": "Malaysia",
        "authority": "NPRA",
        "category": "Documents",
        "dimension": "DOCUMENTS",
        "obligation_type": "gmp_certificate",
        "canonical_statement": "A current GMP certificate must be on file.",
        "default_severity": "MAJOR",
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


def _submit_verify_activate(client, writer, path):
    response = client.post(f"{path}/submit-for-review", headers=writer["headers"])
    assert response.status_code == 200

    response = client.post(
        f"{path}/verify",
        json={"rationale": "Verified against primary text."},
        headers=writer["headers"],
    )
    assert response.status_code == 200

    response = client.post(
        f"{path}/activate",
        json={"rationale": "Approved for release inclusion."},
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _activate_requirement_version(client, writer, requirement, version):
    return _submit_verify_activate(
        client, writer, f"/requirements/{requirement['id']}/versions/{version['id']}",
    )


def _create_rule_version(client, writer, requirement_version_id, **overrides):
    rule = client.post("/rules", json={}, headers=writer["headers"]).json()

    payload = {
        "requirement_version_id": requirement_version_id,
        "condition": {"op": "not_exists", "field": "status"},
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
    return _submit_verify_activate(
        client, writer, f"/rules/{rule['id']}/versions/{version['id']}",
    )


def _create_active_release(client, writer, rule_version_ids, requirement_version_ids, category="Documents"):
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
    activated_source = _submit_verify_activate(
        client, writer, f"/sources/{source['id']}/versions/{source_version['id']}",
    )

    response = client.post(
        "/regulatory-basis-releases",
        json={
            "jurisdiction": "Malaysia",
            "market": "Malaysia",
            "category": category,
            "source_version_ids": [activated_source["id"]],
            "requirement_version_ids": requirement_version_ids,
            "rule_version_ids": rule_version_ids,
        },
        headers=writer["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _build_document_rule_only(
    client,
    writer,
    *,
    condition,
    output_type="FINDING_PROPOSAL",
    unknown_behavior="HUMAN_REVIEW",
    default_severity="MAJOR",
    obligation_type="gmp_certificate",
    subject_kind=None,
    **requirement_overrides,
):
    """
    Same as _build_document_rule but without creating a release - for
    tests that need multiple rules combined into a single release (only
    one ACTIVE release per jurisdiction/market is allowed).
    """

    requirement, requirement_version = _create_requirement_version(
        client, writer,
        default_severity=default_severity,
        obligation_type=obligation_type,
        subject_kind=subject_kind,
        **requirement_overrides,
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

    return requirement_version, rule_version


def _build_document_rule(
    client,
    writer,
    *,
    condition,
    output_type="FINDING_PROPOSAL",
    unknown_behavior="HUMAN_REVIEW",
    default_severity="MAJOR",
    obligation_type="gmp_certificate",
    subject_kind=None,
    **requirement_overrides,
):
    requirement_version, rule_version = _build_document_rule_only(
        client, writer,
        condition=condition,
        output_type=output_type,
        unknown_behavior=unknown_behavior,
        default_severity=default_severity,
        obligation_type=obligation_type,
        subject_kind=subject_kind,
        **requirement_overrides,
    )

    release = _create_active_release(
        client, writer,
        rule_version_ids=[rule_version["id"]],
        requirement_version_ids=[requirement_version["id"]],
    )

    return requirement_version, rule_version, release


def _run_assessment(client, tenant, state_id, documents=None, consistency_checks=None, product_facts=None):
    response = client.post(
        "/assessment-runs",
        json={
            "product_market_state_id": state_id,
            "dimensions": ["DOCUMENTS"],
            "input_facts": {
                "DOCUMENTS": {
                    "product": product_facts or {},
                    "documents": documents or [],
                    "consistency_checks": consistency_checks or [],
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


def test_missing_mandatory_document_proposes_finding(client, tenant_a, regulatory_content_writer):
    _build_document_rule(
        client, regulatory_content_writer,
        condition={"op": "not_exists", "field": "status"},
        output_type="FINDING_PROPOSAL",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    # No documents submitted at all - the checklist item still gets
    # evaluated (derived from the regulatory basis, not the caller's list).
    run = _run_assessment(client, tenant_a, state["id"], documents=[])
    assert run["status"] == "COMPLETED"

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    step = detail["step_runs"][0]
    assert step["subject_key"] == "gmp_certificate"
    assert step["outcome"] == "MATCH"
    assert step["input_facts"] == {"product": {}, "document_type": "gmp_certificate"}

    findings = _get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1
    assert findings[0]["subject_key"] == "gmp_certificate"


def test_uploaded_document_satisfies_checklist_no_finding(client, tenant_a, regulatory_content_writer):
    _build_document_rule(
        client, regulatory_content_writer,
        condition={"op": "not_exists", "field": "status"},
        output_type="FINDING_PROPOSAL",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        documents=[{
            "document_type": "gmp_certificate",
            "status": "uploaded",
            "manufacturer": {"value": "Acme Corp", "confidence": 0.9},
        }],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert detail["dimension_assessments"][0]["state"] == "COMPLIANT"
    assert _get_findings(client, tenant_a, state["id"]) == []


def test_low_confidence_document_field_hard_pins_human_review(client, tenant_a, regulatory_content_writer):
    """
    Confirms the AC-FR-06-02 hard-pin generalizes to Documents (explicitly
    confirmed): FR-08 relies on extracted data the same way Label relies
    on OCR, so uncertain extraction shouldn't satisfy a mandatory check
    here either. Mirrors test_low_confidence_overrides_fail_closed_
    requirement_result in test_assessment_run_label.py.
    """

    _build_document_rule(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "manufacturer", "value": "Acme Corp"},
        output_type="REQUIREMENT_RESULT",
        unknown_behavior="FAIL_CLOSED",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        documents=[{
            "document_type": "gmp_certificate",
            "status": "uploaded",
            "manufacturer": {"value": "Acme Corp", "confidence": 0.2},
        }],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    step = detail["step_runs"][0]
    assert step["outcome"] == "UNKNOWN"
    assert step["trace"][0]["reason"] == "low_confidence"
    assert detail["dimension_assessments"][0]["state"] == "HUMAN_REVIEW_REQUIRED"


def test_consistency_check_mismatch_proposes_finding(client, tenant_a, regulatory_content_writer):
    _build_document_rule(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "outcome", "value": "MISMATCH"},
        output_type="FINDING_PROPOSAL",
        obligation_type="manufacturer_consistency",
        subject_kind="CONSISTENCY_CHECK",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        consistency_checks=[{
            "check_key": "manufacturer_gmp_vs_cfs",
            "compared_field": "manufacturer",
            "value_a": "Acme Corp",
            "value_b": "Acme Corporation",
            "document_types": ["gmp_certificate", "cfs"],
            "outcome": {"value": "MISMATCH", "confidence": 0.88},
        }],
    )
    assert run["status"] == "COMPLETED"

    findings = _get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1
    assert findings[0]["subject_key"] == "manufacturer_gmp_vs_cfs"


def test_consistency_and_document_requirements_route_to_correct_subject_pools(client, tenant_a, regulatory_content_writer):
    """
    The routing guarantee subject_kind exists for: a CONSISTENCY_CHECK-
    kind requirement's rule must never run against a document checklist
    subject, and a DOCUMENT-kind (default) requirement's rule must never
    run against a consistency_checks[] subject. If either crossed over,
    it would resolve UNKNOWN against fields that don't exist for that
    subject shape, and this run would produce 4 StepRuns instead of 2.
    """

    doc_requirement_version, doc_rule_version = _build_document_rule_only(
        client, regulatory_content_writer,
        condition={"op": "not_exists", "field": "status"},
        output_type="FINDING_PROPOSAL",
        obligation_type="gmp_certificate",
        subject_kind=None,
    )
    consistency_requirement_version, consistency_rule_version = _build_document_rule_only(
        client, regulatory_content_writer,
        condition={"op": "equals", "field": "outcome", "value": "MISMATCH"},
        output_type="FINDING_PROPOSAL",
        obligation_type="manufacturer_consistency",
        subject_kind="CONSISTENCY_CHECK",
    )

    # Only one ACTIVE release is allowed per jurisdiction/market - combine
    # both rules into a single release so both are active for the same run.
    source = client.post("/sources", headers=regulatory_content_writer["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Combined Source",
            "issuing_authority": "Test Authority",
            "jurisdiction": "Malaysia",
            "tier": 1,
            "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=regulatory_content_writer["headers"],
    ).json()
    activated_source = _submit_verify_activate(
        client, regulatory_content_writer,
        f"/sources/{source['id']}/versions/{source_version['id']}",
    )
    release_response = client.post(
        "/regulatory-basis-releases",
        json={
            "jurisdiction": "Malaysia",
            "market": "Malaysia",
            "category": "Documents",
            "source_version_ids": [activated_source["id"]],
            "requirement_version_ids": [doc_requirement_version["id"], consistency_requirement_version["id"]],
            "rule_version_ids": [doc_rule_version["id"], consistency_rule_version["id"]],
        },
        headers=regulatory_content_writer["headers"],
    )
    assert release_response.status_code == 200

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = client.post(
        f"/products/{product['id']}/market-states",
        json={"product_version_id": version["id"], "market": "Malaysia", "jurisdiction": "Malaysia"},
        headers=tenant_a["headers"],
    ).json()

    run = _run_assessment(
        client, tenant_a, state["id"],
        documents=[{"document_type": "gmp_certificate", "status": "uploaded"}],
        consistency_checks=[{
            "check_key": "manufacturer_check",
            "outcome": {"value": "MISMATCH", "confidence": 0.9},
        }],
    )
    assert run["status"] == "COMPLETED"

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    steps = detail["step_runs"]
    assert len(steps) == 2

    by_subject = {step["subject_key"]: step for step in steps}
    assert set(by_subject) == {"gmp_certificate", "manufacturer_check"}

    # The doc rule ran only against the document subject (status present -> NO_MATCH).
    assert by_subject["gmp_certificate"]["rule_version_id"] == doc_rule_version["id"]
    assert by_subject["gmp_certificate"]["outcome"] == "NO_MATCH"

    # The consistency rule ran only against the consistency subject (outcome MISMATCH -> MATCH).
    assert by_subject["manufacturer_check"]["rule_version_id"] == consistency_rule_version["id"]
    assert by_subject["manufacturer_check"]["outcome"] == "MATCH"


def test_extra_submitted_document_without_checklist_rule_is_ignored(client, tenant_a, regulatory_content_writer):
    _build_document_rule(
        client, regulatory_content_writer,
        condition={"op": "not_exists", "field": "status"},
        output_type="FINDING_PROPOSAL",
        obligation_type="gmp_certificate",
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    run = _run_assessment(
        client, tenant_a, state["id"],
        documents=[
            {"document_type": "gmp_certificate", "status": "uploaded"},
            {"document_type": "cfs", "status": "uploaded"},  # no checklist rule for "cfs"
        ],
    )

    detail = _get_run_detail(client, tenant_a, state["id"], run["id"])
    assert len(detail["step_runs"]) == 1
    assert detail["step_runs"][0]["subject_key"] == "gmp_certificate"


def test_build_document_facts_missing_document_yields_document_type_only(db):
    service = AssessmentRunService(db)

    facts = service._build_document_facts("gmp_certificate", None, datetime.now(timezone.utc))
    assert facts == {"document_type": "gmp_certificate"}


def test_build_document_facts_omits_field_with_null_value(db):
    service = AssessmentRunService(db)

    facts = service._build_document_facts(
        "gmp_certificate",
        {
            "document_type": "gmp_certificate",
            "status": "uploaded",
            "manufacturer": {"value": None, "confidence": 0.0},
        },
        datetime.now(timezone.utc),
    )
    assert "manufacturer" not in facts
    assert facts["status"] == "uploaded"


def test_build_document_facts_keeps_field_with_present_value(db):
    service = AssessmentRunService(db)

    facts = service._build_document_facts(
        "gmp_certificate",
        {
            "document_type": "gmp_certificate",
            "status": "uploaded",
            "manufacturer": {"value": "Acme Corp", "confidence": 0.9},
        },
        datetime.now(timezone.utc),
    )
    assert facts["manufacturer"] == {"value": "Acme Corp", "confidence": 0.9}


def test_build_document_facts_computes_days_until_expiry(db):
    service = AssessmentRunService(db)
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    facts = service._build_document_facts(
        "gmp_certificate",
        {
            "document_type": "gmp_certificate",
            "status": "uploaded",
            "expiry_date": {"value": "2026-01-31", "confidence": 0.9},
        },
        started_at,
    )
    assert facts["days_until_expiry"] == {"value": 30, "confidence": 0.9}


def test_build_document_facts_days_until_expiry_negative_when_already_expired(db):
    service = AssessmentRunService(db)
    started_at = datetime(2026, 2, 1, tzinfo=timezone.utc)

    facts = service._build_document_facts(
        "gmp_certificate",
        {
            "document_type": "gmp_certificate",
            "status": "uploaded",
            "expiry_date": {"value": "2026-01-01", "confidence": 0.9},
        },
        started_at,
    )
    assert facts["days_until_expiry"]["value"] == -31


def test_hash_facts_is_stable_regardless_of_dict_key_order(db):
    """
    The one property DimensionAssessment.submitted_facts_hash's reuse
    comparison depends on: two dicts with the same content in a
    different key order must hash identically, at every nesting level.
    """
    service = AssessmentRunService(db)

    a = {"product": {"category_id": "cosmetic"}, "claims": [{"claim_id": "c1", "wording": "x"}]}
    b = {"claims": [{"wording": "x", "claim_id": "c1"}], "product": {"category_id": "cosmetic"}}

    assert service.hash_facts(a) == service.hash_facts(b)


def test_hash_facts_differs_for_different_content(db):
    service = AssessmentRunService(db)

    a = {"claims": [{"claim_id": "c1", "wording": "clinically proven"}]}
    b = {"claims": [{"claim_id": "c1", "wording": "a different claim"}]}

    assert service.hash_facts(a) != service.hash_facts(b)


def test_hash_facts_is_sensitive_to_list_order(db):
    """
    Deliberately order-sensitive, not canonicalized - a reordered list
    hashes differently, which only ever costs an unnecessary rerun
    (the safe direction), never a wrongly-skipped one. See CLAUDE.md
    "Market readiness" for the tradeoff.
    """
    service = AssessmentRunService(db)

    a = {"claims": [{"claim_id": "c1", "wording": "x"}, {"claim_id": "c2", "wording": "y"}]}
    b = {"claims": [{"claim_id": "c2", "wording": "y"}, {"claim_id": "c1", "wording": "x"}]}

    assert service.hash_facts(a) != service.hash_facts(b)


def test_hash_facts_is_sensitive_to_confidence(db):
    """
    Confidence is included in the hash, not stripped before hashing -
    a confidence-only revision (same wording/value, different
    confidence) must be treated as different submitted facts, since
    AC-FR-06-02 already treats confidence as load-bearing content, not
    descriptive metadata.
    """
    service = AssessmentRunService(db)

    a = {"label_fields": [{"field_key": "net_quantity", "value": "50 mL", "confidence": 0.95}]}
    b = {"label_fields": [{"field_key": "net_quantity", "value": "50 mL", "confidence": 0.31}]}

    assert service.hash_facts(a) != service.hash_facts(b)
