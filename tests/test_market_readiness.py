from __future__ import annotations

from app.modules.market_readiness.service import MarketReadinessService

# --- Synthetic Market Readiness fixtures only - never real seeded content ---


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


def _publish_version(client, tenant, product_id, version_id):
    response = client.post(
        f"/products/{product_id}/versions/{version_id}/publish",
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


def _update_state(client, tenant, product_id, state_id, **payload):
    response = client.put(
        f"/products/{product_id}/market-states/{state_id}",
        json=payload,
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
        "category": "Claims",
        "dimension": "CLAIMS",
        "obligation_type": "PROHIBITED_THERAPEUTIC_CLAIM",
        "canonical_statement": "Claims must not be therapeutic.",
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
        "condition": {"op": "exists", "field": "wording"},
        "output_type": "REQUIREMENT_RESULT",
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


def _create_active_release(client, tenant, rule_version_ids, requirement_version_ids, market="Malaysia"):
    source = client.post("/sources", headers=tenant["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Test Source",
            "issuing_authority": "Test Authority",
            "jurisdiction": market,
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
            "jurisdiction": market,
            "market": market,
            "source_version_ids": [activated_source["id"]],
            "requirement_version_ids": requirement_version_ids,
            "rule_version_ids": rule_version_ids,
        },
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _build_claims_rule(client, tenant, *, condition, output_type="REQUIREMENT_RESULT", **overrides):
    requirement, requirement_version = _create_requirement_version(client, tenant, **overrides)
    requirement_version = _activate_requirement_version(client, tenant, requirement, requirement_version)

    rule, rule_version = _create_rule_version(
        client, tenant, requirement_version["id"],
        condition=condition, output_type=output_type,
    )
    rule_version = _activate_rule_version(client, tenant, rule, rule_version)

    return requirement_version, rule_version


def _run_market_readiness(client, tenant, state_id, input_facts=None):
    response = client.post(
        "/market-readiness-runs",
        json={
            "product_market_state_id": state_id,
            "input_facts": input_facts or {},
        },
        headers=tenant["headers"],
    )
    return response


def _get_state_snapshots(client, tenant, state_id):
    response = client.get(
        "/state-snapshots",
        params={"product_market_state_id": state_id},
        headers=tenant["headers"],
    )
    assert response.status_code == 200
    return response.json()


def _claims_facts(claim_id="c1", wording="clinically proven"):
    return {"CLAIMS": {"product": {}, "claims": [{"claim_id": claim_id, "wording": wording}]}}


def _setup_ready_state(client, tenant, market="Malaysia"):
    """One CLAIMS requirement/rule, published version, active release, state."""

    requirement_version, rule_version = _build_claims_rule(
        client, tenant,
        condition={"op": "exists", "field": "wording"},
        output_type="REQUIREMENT_RESULT",
        market=market, jurisdiction=market,
    )
    _create_active_release(
        client, tenant,
        rule_version_ids=[rule_version["id"]],
        requirement_version_ids=[requirement_version["id"]],
        market=market,
    )

    product = _create_product(client, tenant)
    version = _create_version(client, tenant, product["id"])
    _publish_version(client, tenant, product["id"], version["id"])
    state = _create_state(client, tenant, product["id"], version["id"], market=market)

    return product, version, state


# --- Preflight -----------------------------------------------------------


def test_preflight_reports_all_failures_not_just_first(client, tenant_a):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    # Not published. No release exists for this market at all, so the
    # state auto-pins nothing (regulatory_basis_release_id stays None).
    state = _create_state(client, tenant_a, product["id"], version["id"])

    response = _run_market_readiness(client, tenant_a, state["id"])
    assert response.status_code == 409

    message = response.json()["error"]["message"]
    assert "PRODUCT_VERSION_NOT_PUBLISHED" in message
    assert "NO_REGULATORY_BASIS" in message


def test_preflight_passes_with_published_version_and_active_release(client, tenant_a):
    _, _, state = _setup_ready_state(client, tenant_a)

    response = _run_market_readiness(client, tenant_a, state["id"], _claims_facts())
    assert response.status_code == 200


# --- Snapshot creation and gate write-back --------------------------------


def test_market_readiness_run_creates_snapshot_and_defaults_to_g0_with_unbuilt_dimensions(client, tenant_a):
    product, version, state = _setup_ready_state(client, tenant_a)

    response = _run_market_readiness(client, tenant_a, state["id"], _claims_facts())
    assert response.status_code == 200
    snapshot = response.json()

    # 7 of 8 canonical dimensions have zero rule content -> Unknown ->
    # forces G0, per B5.3's own "required dimension Unknown" trigger.
    assert snapshot["overall_gate"] == "G0"
    assert "DIMENSION_UNKNOWN" in snapshot["readiness_reason_codes"]
    assert snapshot["dimension_summary"]["CLAIMS"]["state"] == "COMPLIANT"
    assert snapshot["dimension_summary"]["TESTING"]["state"] == "UNKNOWN"
    assert snapshot["displayed_progress"] <= 49.0

    state_detail = client.get(
        f"/products/{product['id']}/market-states/{state['id']}",
        headers=tenant_a["headers"],
    ).json()
    assert state_detail["gate"] == "G0"


# --- Reuse vs rerun --------------------------------------------------------


def test_second_run_reuses_unchanged_dimension(client, tenant_a):
    _, _, state = _setup_ready_state(client, tenant_a)

    first = _run_market_readiness(client, tenant_a, state["id"], _claims_facts()).json()
    # No "CLAIMS" key this time - nothing to rerun with, should reuse.
    second = _run_market_readiness(client, tenant_a, state["id"], {}).json()

    assert second["dimension_summary"]["CLAIMS"]["reused"] is True
    assert (
        second["dimension_summary"]["CLAIMS"]["dimension_assessment_id"]
        == first["dimension_summary"]["CLAIMS"]["dimension_assessment_id"]
    )


def test_supplying_facts_forces_rerun_even_if_otherwise_reusable(client, tenant_a):
    """
    Self-sufficient by construction: run 1 -> 2 (no facts) proves reuse
    is genuinely happening under identical conditions (a control,
    ruling out "reuse is just always broken" as an alternative
    explanation for run 3 also showing reused=False); only run 2 -> 3
    (facts resupplied) isolates the one variable this test is actually
    about.
    """

    _, _, state = _setup_ready_state(client, tenant_a)

    first = _run_market_readiness(client, tenant_a, state["id"], _claims_facts()).json()
    second = _run_market_readiness(client, tenant_a, state["id"], {}).json()
    assert second["dimension_summary"]["CLAIMS"]["reused"] is True

    third = _run_market_readiness(client, tenant_a, state["id"], _claims_facts()).json()
    assert third["dimension_summary"]["CLAIMS"]["reused"] is False
    assert (
        third["dimension_summary"]["CLAIMS"]["dimension_assessment_id"]
        != second["dimension_summary"]["CLAIMS"]["dimension_assessment_id"]
    )


def test_changing_product_version_forces_rerun_and_marks_prior_snapshot_stale(client, tenant_a):
    product, version, state = _setup_ready_state(client, tenant_a)

    first = _run_market_readiness(client, tenant_a, state["id"], _claims_facts()).json()

    new_version = _create_version(client, tenant_a, product["id"], version="2.0.0")
    _publish_version(client, tenant_a, product["id"], new_version["id"])
    _update_state(client, tenant_a, product["id"], state["id"], product_version_id=new_version["id"])

    second = _run_market_readiness(client, tenant_a, state["id"], {}).json()

    # product_version_id changed -> no reusable prior DimensionAssessment
    # pinned to the new version -> rerun, even with no facts supplied.
    assert second["dimension_summary"]["CLAIMS"]["reused"] is False
    assert second["product_version_id"] == new_version["id"]

    snapshots = _get_state_snapshots(client, tenant_a, state["id"])
    by_id = {s["id"]: s for s in snapshots}
    assert by_id[first["id"]]["is_current"] is False
    # Flagged stale twice over: once synchronously by the pin change
    # itself (ProductMarketStateService.update()), then again when the
    # new snapshot actually supersedes it.
    assert by_id[second["id"]]["is_current"] is True


def test_new_snapshot_marks_previous_snapshot_superseded(client, tenant_a):
    _, _, state = _setup_ready_state(client, tenant_a)

    first = _run_market_readiness(client, tenant_a, state["id"], _claims_facts()).json()
    second = _run_market_readiness(client, tenant_a, state["id"], _claims_facts()).json()

    snapshots = _get_state_snapshots(client, tenant_a, state["id"])
    by_id = {s["id"]: s for s in snapshots}

    assert by_id[first["id"]]["is_current"] is False
    assert by_id[first["id"]]["superseded_by_snapshot_id"] == second["id"]
    assert by_id[second["id"]]["is_current"] is True


# --- Scoring (B5.2) --------------------------------------------------------


def test_dimension_score_avoids_double_counting_and_applies_alone_scores_zero(client, tenant_a):
    """
    req_a has TWO rules (APPLICABILITY + REQUIREMENT_RESULT) both
    matching against the same claim - its importance_weight (2.0) must
    be counted once, not twice. req_b's APPLICABILITY rule resolves
    DOES_NOT_APPLY - excluded from the denominator entirely. req_c has
    only an APPLICABILITY rule that matches (APPLIES) with no
    REQUIREMENT_RESULT rule - APPLIES alone earns no credit.

    Expected: weighted_sum = 1.0*2.0 (req_a, satisfied) + 0.0*1.0 (req_c)
    = 2.0; weight_total = 2.0 + 1.0 (req_b excluded) = 3.0;
    score = round(2.0/3.0*100, 2) = 66.67.
    """

    req_a, applicability_rule_a = _build_claims_rule(
        client, tenant_a,
        condition={"op": "exists", "field": "wording"},
        output_type="APPLICABILITY",
        obligation_type="REQ_A", importance_weight=2.0,
    )
    satisfaction_rule_a_parent, satisfaction_rule_a = _create_rule_version(
        client, tenant_a, req_a["id"],
        condition={"op": "equals", "field": "wording", "value": "clinically proven"},
        output_type="REQUIREMENT_RESULT",
    )
    satisfaction_rule_a = _activate_rule_version(
        client, tenant_a, satisfaction_rule_a_parent, satisfaction_rule_a,
    )

    req_b, applicability_rule_b = _build_claims_rule(
        client, tenant_a,
        condition={"op": "equals", "field": "wording", "value": "no such value"},
        output_type="APPLICABILITY",
        obligation_type="REQ_B", importance_weight=1.0,
    )

    req_c, applicability_rule_c = _build_claims_rule(
        client, tenant_a,
        condition={"op": "exists", "field": "wording"},
        output_type="APPLICABILITY",
        obligation_type="REQ_C", importance_weight=1.0,
    )

    _create_active_release(
        client, tenant_a,
        rule_version_ids=[
            applicability_rule_a["id"], satisfaction_rule_a["id"],
            applicability_rule_b["id"], applicability_rule_c["id"],
        ],
        requirement_version_ids=[req_a["id"], req_b["id"], req_c["id"]],
    )

    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    _publish_version(client, tenant_a, product["id"], version["id"])
    state = _create_state(client, tenant_a, product["id"], version["id"])

    response = _run_market_readiness(client, tenant_a, state["id"], _claims_facts())
    assert response.status_code == 200
    snapshot = response.json()

    assert snapshot["dimension_summary"]["CLAIMS"]["score"] == 66.67


# --- Gate computation (unit-level - synthetic inputs, no full 8-dimension setup) ---


def test_compute_gate_critical_finding_forces_g1_regardless_of_progress(db):
    service = MarketReadinessService(db)
    dimension_summary = {"CLAIMS": {"state": "COMPLIANT"}}
    open_findings = [{"severity": "CRITICAL", "status": "PROPOSED"}]

    gate, reasons = service._compute_gate(dimension_summary, open_findings)
    assert gate == "G1"
    assert "CRITICAL_FINDING_OPEN" in reasons


def test_compute_gate_proposed_status_blocks_same_as_open(db):
    """
    Resolution: non-dispositioned statuses block the gate, not just
    literal "OPEN" - PROPOSED is the only status the engine's Finding
    proposal mechanism ever actually writes (no RA-review workflow
    exists to move it further), so gating strictly on "OPEN" would make
    G1 permanently unreachable.
    """

    service = MarketReadinessService(db)
    dimension_summary = {"CLAIMS": {"state": "COMPLIANT"}}
    open_findings = [{"severity": "CRITICAL", "status": "PROPOSED"}]

    gate, _ = service._compute_gate(dimension_summary, open_findings)
    assert gate == "G1"


def test_compute_gate_g1_reasons_include_both_critical_finding_and_non_compliant_dimension(db):
    """
    Both G1 triggers present at once must both surface as reason codes,
    not just whichever is checked first - readiness_reason_codes is
    meant to explain every contributing cause, same "report all, not
    just first" spirit as preflight.
    """

    service = MarketReadinessService(db)
    dimension_summary = {"CLAIMS": {"state": "NON_COMPLIANT"}}
    open_findings = [{"severity": "CRITICAL", "status": "PROPOSED"}]

    gate, reasons = service._compute_gate(dimension_summary, open_findings)
    assert gate == "G1"
    assert "CRITICAL_FINDING_OPEN" in reasons
    assert "NON_COMPLIANT_DIMENSION" in reasons


def test_compute_gate_major_finding_forces_g2(db):
    service = MarketReadinessService(db)
    dimension_summary = {"CLAIMS": {"state": "COMPLIANT"}}
    open_findings = [{"severity": "MAJOR", "status": "OPEN"}]

    gate, reasons = service._compute_gate(dimension_summary, open_findings)
    assert gate == "G2"
    assert "MAJOR_FINDING_OPEN" in reasons


def test_compute_gate_human_review_dimension_forces_g3(db):
    service = MarketReadinessService(db)
    dimension_summary = {"CLAIMS": {"state": "HUMAN_REVIEW_REQUIRED"}}

    gate, reasons = service._compute_gate(dimension_summary, [])
    assert gate == "G3"
    assert "HUMAN_REVIEW_REQUIRED" in reasons


def test_compute_gate_g4_and_g5_are_unreachable_even_when_all_conditions_met(db):
    """
    Resolution: G4/G5 explicitly blocked this pass - absence of an
    Approval model is not the same as approvals being satisfied. Even
    with every dimension COMPLIANT and zero open findings (the objective
    best case), the gate must cap at G3, with a reason code distinct
    from the real HUMAN_REVIEW_REQUIRED case.
    """

    service = MarketReadinessService(db)
    dimension_summary = {dim: {"state": "COMPLIANT"} for dim in [
        "CLASSIFICATION_ELIGIBILITY", "INGREDIENTS", "CLAIMS", "LABEL",
        "DOCUMENTS", "TESTING", "REPRESENTATION", "REGISTRATION_READINESS",
    ]}

    gate, reasons = service._compute_gate(dimension_summary, [])
    assert gate == "G3"
    assert "G4_UNREACHABLE_NO_APPROVAL_MODEL" in reasons
    assert "HUMAN_REVIEW_REQUIRED" not in reasons
