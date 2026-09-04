from __future__ import annotations

"""
Golden-case regression suite for the TESTLAND synthetic corpus. See
tests/testland/README.md for the corpus design writeup (Tier A/B
coverage limits, the medical-device pathway-fit analysis, the
reuse-forcing convention this file follows: one fresh Product/
ProductVersion/ProductMarketState per golden case, exactly one
market-readiness run each).

"Passing" means overall_gate == "G3" AND readiness_reason_codes ==
["G4_UNREACHABLE_NO_APPROVAL_MODEL"] specifically - G3 alone is not
enough, since the human-review golden cases also land on G3 with a
different reason code. Every test asserts both.
"""

import pytest

from tests.testland import fixtures as tl


@pytest.fixture()
def beauty(client, regulatory_content_writer):
    return tl.build_beauty_content(client, regulatory_content_writer)


@pytest.fixture()
def nutra(client, regulatory_content_writer):
    return tl.build_nutra_content(client, regulatory_content_writer)


@pytest.fixture()
def meddevice(client, regulatory_content_writer):
    return tl.build_meddevice_content(client, regulatory_content_writer)


def _passing(snapshot):
    assert snapshot["overall_gate"] == "G3"
    assert snapshot["readiness_reason_codes"] == ["G4_UNREACHABLE_NO_APPROVAL_MODEL"]


# --- Beauty / personal care - control case ----------------------------------


def _beauty_filler_facts():
    """The five canonical dimensions Beauty has no distinctive content
    for - see build_filler_requirement. Every golden case needs these
    satisfied or the run caps at G0 regardless of CLAIMS/LABEL/
    INGREDIENTS."""

    return {
        "CLASSIFICATION_ELIGIBILITY": {"product": {}, "category_confirmed_ref": "CAT-1"},
        "DOCUMENTS": {"product": {},
                      "documents": [{"document_type": "product_safety_report", "status": "uploaded"}],
                      "consistency_checks": []},
        "TESTING": {"product": {}, "stability_test_ref": "STAB-1"},
        "REPRESENTATION": {"product": {}, "artwork_approved_ref": "ART-1"},
        "REGISTRATION_READINESS": {"product": {}, "responsible_person_ref": "RP-1"},
    }


def _beauty_facts(*, wording, packaging_type="retail", net_quantity_confidence=0.95):
    return {
        "CLAIMS": {"product": {}, "claims": [{"claim_id": "c1", "wording": wording}]},
        "LABEL": {"product": {"packaging_type": packaging_type},
                  "label_fields": [{"field_key": "net_quantity", "value": "50 mL",
                                     "confidence": net_quantity_confidence}]},
        "INGREDIENTS": {"product": {}, "claims": [{"claim_id": "ing-1", "ingredient_name": "Aqua"}]},
        **_beauty_filler_facts(),
    }


def test_beauty_passing(client, tenant_a, beauty):
    _, _, state = tl.new_golden_product(client, tenant_a, "Beauty Passing", tl.MARKET_BEAUTY)

    input_facts = _beauty_facts(wording="Softens and smooths skin")
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    _passing(snapshot)
    assert tl.get_findings(client, tenant_a, state["id"]) == []


def test_beauty_critical_fail(client, tenant_a, beauty):
    _, _, state = tl.new_golden_product(client, tenant_a, "Beauty Critical", tl.MARKET_BEAUTY)

    input_facts = _beauty_facts(wording="Cures Acne")
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    assert snapshot["overall_gate"] == "G1"
    assert set(snapshot["readiness_reason_codes"]) == {
        "CRITICAL_FINDING_OPEN", "HARD_GATE_FINDING_OPEN", "NON_COMPLIANT_DIMENSION",
    }
    findings = tl.get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1


def test_beauty_human_review(client, tenant_a, beauty):
    _, _, state = tl.new_golden_product(client, tenant_a, "Beauty HumanReview", tl.MARKET_BEAUTY)

    input_facts = _beauty_facts(wording="Softens and smooths skin", net_quantity_confidence=0.2)
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    assert snapshot["overall_gate"] == "G3"
    assert snapshot["readiness_reason_codes"] == ["HUMAN_REVIEW_REQUIRED"]
    assert snapshot["dimension_summary"]["LABEL"]["state"] == "HUMAN_REVIEW_REQUIRED"
    assert tl.get_findings(client, tenant_a, state["id"]) == []


def test_beauty_not_applicable(client, tenant_a, beauty):
    _, _, state = tl.new_golden_product(client, tenant_a, "Beauty NotApplicable", tl.MARKET_BEAUTY)

    input_facts = _beauty_facts(wording="Softens and smooths skin", packaging_type="bulk")
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    # Not-applicable for bulk packaging - and still passing overall,
    # proving the exclusion works rather than being treated as a
    # compliance gap. See module docstring on why this asserts the
    # underlying StepRun rather than a whole-dimension NOT_APPLICABLE
    # state (LABEL's other, always-applicable requirement keeps the
    # dimension COMPLIANT, correctly - NOT_APPLICABLE at the dimension
    # level requires every requirement in it to be inapplicable at once).
    _passing(snapshot)
    detail = tl.get_run_detail(client, tenant_a, state["id"], snapshot["assessment_run_id"])
    applicability_rule_id = beauty["rule_versions"]["label_allergen_applicability"]["id"]
    applicability_steps = [s for s in detail["step_runs"] if s["rule_version_id"] == applicability_rule_id]
    assert applicability_steps and all(s["outcome"] == "NO_MATCH" for s in applicability_steps)


# --- Nutraceuticals ----------------------------------------------------------


def _nutra_filler_facts():
    """The five canonical dimensions Nutraceuticals has no distinctive
    content for - see build_filler_requirement."""

    return {
        "CLASSIFICATION_ELIGIBILITY": {"product": {}, "category_confirmed_ref": "CAT-1"},
        "DOCUMENTS": {"product": {},
                      "documents": [{"document_type": "product_safety_report", "status": "uploaded"}],
                      "consistency_checks": []},
        "TESTING": {"product": {}, "stability_test_ref": "STAB-1"},
        "REPRESENTATION": {"product": {}, "artwork_approved_ref": "ART-1"},
        "REGISTRATION_READINESS": {"product": {}, "responsible_person_ref": "RP-1"},
    }


def _nutra_facts(*, dosage_mg, wording, serving_size_confidence=0.9, intended_use="oral", batch_reference="BATCH-1"):
    facts = {
        "INGREDIENTS": {"product": {}, "daily_dosage_mg": dosage_mg, "batch_reference": batch_reference},
        "CLAIMS": {"product": {}, "claims": [{"claim_id": "c1", "wording": wording}]},
        "LABEL": {"product": {"intended_use": intended_use},
                  "label_fields": [{"field_key": "serving_size", "value": "1 capsule",
                                     "confidence": serving_size_confidence}]},
        **_nutra_filler_facts(),
    }
    return facts


def test_nutra_passing(client, tenant_a, nutra):
    _, _, state = tl.new_golden_product(client, tenant_a, "Nutra Passing", tl.MARKET_NUTRA)

    input_facts = _nutra_facts(dosage_mg=500, wording="Supports normal energy metabolism")
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    _passing(snapshot)
    assert tl.get_findings(client, tenant_a, state["id"]) == []


def test_nutra_critical_fail(client, tenant_a, nutra):
    _, _, state = tl.new_golden_product(client, tenant_a, "Nutra Critical", tl.MARKET_NUTRA)

    input_facts = _nutra_facts(dosage_mg=2500, wording="Supports normal energy metabolism")
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    assert snapshot["overall_gate"] == "G1"
    assert "CRITICAL_FINDING_OPEN" in snapshot["readiness_reason_codes"]
    assert "HARD_GATE_FINDING_OPEN" in snapshot["readiness_reason_codes"]
    findings = tl.get_findings(client, tenant_a, state["id"])
    assert len(findings) >= 1


def test_nutra_human_review(client, tenant_a, nutra):
    _, _, state = tl.new_golden_product(client, tenant_a, "Nutra HumanReview", tl.MARKET_NUTRA)

    input_facts = _nutra_facts(
        dosage_mg=500, wording="Supports normal energy metabolism", serving_size_confidence=0.2,
    )
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    assert snapshot["overall_gate"] == "G3"
    assert snapshot["readiness_reason_codes"] == ["HUMAN_REVIEW_REQUIRED"]
    assert snapshot["dimension_summary"]["LABEL"]["state"] == "HUMAN_REVIEW_REQUIRED"
    assert tl.get_findings(client, tenant_a, state["id"]) == []


def test_nutra_not_applicable(client, tenant_a, nutra):
    _, _, state = tl.new_golden_product(client, tenant_a, "Nutra NotApplicable", tl.MARKET_NUTRA)

    input_facts = _nutra_facts(
        dosage_mg=500, wording="Supports normal energy metabolism", intended_use="topical",
    )
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    _passing(snapshot)
    detail = tl.get_run_detail(client, tenant_a, state["id"], snapshot["assessment_run_id"])
    applicability_rule_id = nutra["rule_versions"]["panel_applicability"]["id"]
    applicability_steps = [s for s in detail["step_runs"] if s["rule_version_id"] == applicability_rule_id]
    assert applicability_steps and all(s["outcome"] == "NO_MATCH" for s in applicability_steps)


# --- Medical devices - the centerpiece ---------------------------------------


def _meddevice_filler_facts():
    """The four canonical dimensions Medical Devices has no distinctive
    content for - see build_filler_requirement. None of these are
    gated by device_risk_class - they're unconditional filler."""

    return {
        "INGREDIENTS": {"product": {}, "materials_ref": "MAT-1"},
        "CLAIMS": {"product": {}, "performance_claim_review_ref": "PCR-1"},
        "LABEL": {"product": {},
                  "label_fields": [{"field_key": "udi", "value": "UDI-000123", "confidence": 0.9}]},
        "REPRESENTATION": {"product": {}, "instructions_for_use_ref": "IFU-1"},
    }


def _meddevice_facts(*, risk_class, confidence, documents=None, consistency_checks=None,
                      bench_test_report_ref=None, notified_body_signoff_ref=None, self_declaration_ref=None):
    classification = {"value": risk_class, "confidence": confidence}
    testing_facts = {"product": {"device_risk_class": classification}}
    if bench_test_report_ref is not None:
        testing_facts["bench_test_report_ref"] = bench_test_report_ref

    registration_facts = {"product": {"device_risk_class": classification}}
    if notified_body_signoff_ref is not None:
        registration_facts["notified_body_signoff_ref"] = notified_body_signoff_ref
    if self_declaration_ref is not None:
        registration_facts["self_declaration_ref"] = self_declaration_ref

    return {
        "CLASSIFICATION_ELIGIBILITY": {"product": {"device_risk_class": classification}},
        "TESTING": testing_facts,
        "REGISTRATION_READINESS": registration_facts,
        "DOCUMENTS": {"product": {"device_risk_class": classification},
                      "documents": documents or [], "consistency_checks": consistency_checks or []},
        **_meddevice_filler_facts(),
    }


def test_meddevice_passing_class_i(client, tenant_a, meddevice):
    _, _, state = tl.new_golden_product(client, tenant_a, "MedDevice Passing", tl.MARKET_MEDDEVICE)

    input_facts = _meddevice_facts(risk_class="I", confidence=0.95, self_declaration_ref="SD-1")
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    _passing(snapshot)
    assert tl.get_findings(client, tenant_a, state["id"]) == []


def test_meddevice_critical_fail_class_iii_missing_clinical_evidence(client, tenant_a, meddevice):
    _, _, state = tl.new_golden_product(client, tenant_a, "MedDevice Critical", tl.MARKET_MEDDEVICE)

    # Clinical evidence report deliberately omitted from documents[];
    # bench test / notified-body refs are supplied so only the one
    # hard-gate Critical finding fires, keeping this case focused.
    input_facts = _meddevice_facts(
        risk_class="III", confidence=0.95,
        bench_test_report_ref="BTR-1", notified_body_signoff_ref="NB-1",
    )
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    assert snapshot["overall_gate"] == "G1"
    assert "CRITICAL_FINDING_OPEN" in snapshot["readiness_reason_codes"]
    assert "HARD_GATE_FINDING_OPEN" in snapshot["readiness_reason_codes"]
    findings = tl.get_findings(client, tenant_a, state["id"])
    assert len(findings) == 1


def test_meddevice_human_review_low_confidence_classification(client, tenant_a, meddevice):
    _, _, state = tl.new_golden_product(client, tenant_a, "MedDevice HumanReview", tl.MARKET_MEDDEVICE)

    # Every Class-III-conditional document/reference is supplied as
    # PRESENT, so each gated rule's own "not_exists" leg resolves a
    # definite NO_MATCH - which wins over the classification leg's
    # low-confidence UNKNOWN in the `all` combinator (NO_MATCH always
    # wins regardless of sibling UNKNOWNs). Only CLASSIFICATION_
    # ELIGIBILITY's bare `equals` rule has no such sibling to shield it,
    # so only that one dimension reads HUMAN_REVIEW_REQUIRED - this is
    # deliberate, not incidental; see README for why.
    input_facts = _meddevice_facts(
        risk_class="III", confidence=0.3,
        documents=[{"document_type": "clinical_evidence_report", "status": "uploaded"}],
        bench_test_report_ref="BTR-1", notified_body_signoff_ref="NB-1",
        self_declaration_ref="SD-1",
    )
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    assert snapshot["overall_gate"] == "G3"
    assert snapshot["readiness_reason_codes"] == ["HUMAN_REVIEW_REQUIRED"]
    assert snapshot["dimension_summary"]["CLASSIFICATION_ELIGIBILITY"]["state"] == "HUMAN_REVIEW_REQUIRED"
    assert tl.get_findings(client, tenant_a, state["id"]) == []


def test_meddevice_not_applicable_class_i_excluded_from_class_iii_eligibility(client, tenant_a, meddevice):
    _, _, state = tl.new_golden_product(client, tenant_a, "MedDevice NotApplicable", tl.MARKET_MEDDEVICE)

    input_facts = _meddevice_facts(risk_class="I", confidence=0.95, self_declaration_ref="SD-1")
    snapshot = tl.run_market_readiness(client, tenant_a, state["id"], input_facts)

    _passing(snapshot)
    detail = tl.get_run_detail(client, tenant_a, state["id"], snapshot["assessment_run_id"])
    classification_rule_id = meddevice["rule_versions"]["classification_iii"]["id"]
    classification_steps = [s for s in detail["step_runs"] if s["rule_version_id"] == classification_rule_id]
    assert classification_steps and all(s["outcome"] == "NO_MATCH" for s in classification_steps)
