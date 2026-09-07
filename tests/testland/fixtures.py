from __future__ import annotations

"""
Content builders for the TESTLAND synthetic corpus - a fictional
jurisdiction used ONLY to exercise the assessment engine end to end
across three categories with genuinely different regulatory shapes.
Never real content. See tests/testland/README.md for the full design
writeup (Tier A/B coverage limits, the medical-device pathway-fit
analysis, the reuse-forcing convention).

Every SourceVersion/RequirementVersion/RuleVersion's notes field carries
SYNTHETIC_NOTE below, so no row from this corpus can be mistaken for
real regulatory content in any admin/list view. Structural provenance
(the actual deletion key) is `jurisdiction` == JURISDICTION ("TESTLAND")
on every RequirementVersion/SourceVersion/RegulatoryBasisRelease, plus
one dedicated Organization owning all customer-side rows - see
scripts/delete_testland_corpus.py.

jurisdiction is the plain constant "TESTLAND" for all three categories,
not a per-category composite like the old "TESTLAND-BEAUTY" - see
CLAUDE.md "Category scoping". Before that fix, ProductMarketState had
only one "market" field and its auto-pin lookup passed that single
value as BOTH the jurisdiction and market argument, so each category
needed its own distinct jurisdiction/market string to pin against the
right release; now that ProductVersion.category and
ProductMarketState.jurisdiction are real, separate fields, the three
categories share one jurisdiction and are told apart by category alone,
same as real multi-category content would be.

These functions are HTTP-based (client + writer headers), matching the
convention every other test_assessment_run_*.py/test_market_readiness.py
file already uses - NOT the direct-service-call convention
scripts/bootstrap_interim_operator.py uses, since these need to exercise
the real API surface (RBAC, validation) as part of "end to end".
scripts/seed_testland_corpus.py reuses these same functions against a
real backend via TestClient(app), not a separate implementation.
"""

JURISDICTION = "TESTLAND"
AUTHORITY = "Testland Bureau of Product Safety (TBPS)"

SYNTHETIC_NOTE = (
    "[REGNOVA-SYNTHETIC-CORPUS:TESTLAND] Fictional content for engine "
    "testing. Not a real regulation."
)

CATEGORY_BEAUTY = "Beauty"
CATEGORY_NUTRA = "Nutraceuticals"
CATEGORY_MEDDEVICE = "Medical Devices"

# Shared with scripts/seed_testland_corpus.py and
# scripts/delete_testland_corpus.py - the customer-side half of the
# corpus's deletion key (see module docstring above).
DEMO_ORG_NAME = "[REGNOVA-SYNTHETIC-CORPUS:TESTLAND] Demo tenant"


# --- Generic content-authoring helpers -------------------------------------


def create_requirement_version(client, writer, *, category, **overrides):
    requirement = client.post("/requirements", json={}, headers=writer["headers"]).json()

    payload = {
        "jurisdiction": JURISDICTION,
        "market": JURISDICTION,
        "authority": AUTHORITY,
        "category": category,
        "authority_interpretation_label": "REGNOVA_INTERPRETATION",
        "notes": SYNTHETIC_NOTE,
    }
    payload.update(overrides)

    response = client.post(
        f"/requirements/{requirement['id']}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return requirement, response.json()


def _submit_verify_activate(client, writer, path):
    """
    DRAFT -> IN_REVIEW -> VERIFIED -> ACTIVE via the real approval
    workflow endpoints (see CLAUDE.md "Regulatory content approval
    workflow") - the corpus's `writer` holds REGULATORY_KNOWLEDGE_LEAD,
    which satisfies both author and verifier authority, so one actor
    runs the whole pipeline here exactly as it can in the real app.
    """
    response = client.post(f"{path}/submit-for-review", headers=writer["headers"])
    assert response.status_code == 200, response.text

    response = client.post(
        f"{path}/verify",
        json={"rationale": SYNTHETIC_NOTE},
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"{path}/activate",
        json={"rationale": SYNTHETIC_NOTE},
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def activate_requirement_version(client, writer, requirement, version):
    return _submit_verify_activate(
        client, writer, f"/requirements/{requirement['id']}/versions/{version['id']}",
    )


def create_rule_version(client, writer, requirement_version_id, **overrides):
    rule = client.post("/rules", json={}, headers=writer["headers"]).json()

    payload = {
        "requirement_version_id": requirement_version_id,
        "notes": SYNTHETIC_NOTE,
    }
    payload.update(overrides)

    response = client.post(
        f"/rules/{rule['id']}/versions",
        json=payload,
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return rule, response.json()


def activate_rule_version(client, writer, rule, version):
    return _submit_verify_activate(
        client, writer, f"/rules/{rule['id']}/versions/{version['id']}",
    )


def build_requirement_and_rule(client, writer, *, category, requirement_overrides, rule_overrides):
    """One Requirement, one Rule, both created and activated - the common case."""

    requirement, requirement_version = create_requirement_version(
        client, writer, category=category, **requirement_overrides,
    )
    requirement_version = activate_requirement_version(client, writer, requirement, requirement_version)

    rule, rule_version = create_rule_version(client, writer, requirement_version["id"], **rule_overrides)
    rule_version = activate_rule_version(client, writer, rule, rule_version)

    return requirement_version, rule_version


def create_active_release(client, writer, *, category, rule_version_ids, requirement_version_ids):
    source = client.post("/sources", headers=writer["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": f"[SYNTHETIC TEST FIXTURE] Testland Product Safety Code - {category}",
            "issuing_authority": AUTHORITY,
            "jurisdiction": JURISDICTION,
            "tier": 1,
            "source_type": "OFFICIAL_GUIDELINE",
            "official_url": f"https://regulations.testland.example/{category.lower().replace(' ', '-')}",
            "notes": SYNTHETIC_NOTE,
        },
        headers=writer["headers"],
    ).json()
    activated_source = _submit_verify_activate(
        client, writer, f"/sources/{source['id']}/versions/{source_version['id']}",
    )

    response = client.post(
        "/regulatory-basis-releases",
        json={
            "jurisdiction": JURISDICTION,
            "market": JURISDICTION,
            "category": category,
            "source_version_ids": [activated_source["id"]],
            "requirement_version_ids": requirement_version_ids,
            "rule_version_ids": rule_version_ids,
        },
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- Product / market-state helpers -----------------------------------------


def create_product(client, tenant, name):
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def create_version(client, tenant, product_id, category, version="1.0.0"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "category": category},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def publish_version(client, tenant, product_id, version_id):
    response = client.post(
        f"/products/{product_id}/versions/{version_id}/publish",
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_state(client, tenant, product_id, product_version_id, jurisdiction=JURISDICTION):
    response = client.post(
        f"/products/{product_id}/market-states",
        json={
            "product_version_id": product_version_id,
            "market": jurisdiction,
            "jurisdiction": jurisdiction,
        },
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def new_golden_product(client, tenant, name, category, version="1.0.0"):
    """One fresh Product/ProductVersion/ProductMarketState per golden
    case - deliberate, not a shared fixture, so reuse never has an
    opportunity to trigger (see README "Reuse / staleness"). category
    selects which of the three category-specific releases this
    product's assessment runs will pin against - jurisdiction is always
    the shared TESTLAND constant (see module docstring)."""

    product = create_product(client, tenant, name)
    version_row = create_version(client, tenant, product["id"], category, version)
    publish_version(client, tenant, product["id"], version_row["id"])
    state = create_state(client, tenant, product["id"], version_row["id"])
    return product, version_row, state


def run_market_readiness(client, tenant, state_id, input_facts):
    response = client.post(
        "/market-readiness-runs",
        json={"product_market_state_id": state_id, "input_facts": input_facts},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def get_run_detail(client, tenant, state_id, run_id):
    response = client.get(
        f"/assessment-runs/{run_id}",
        params={"product_market_state_id": state_id},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def get_findings(client, tenant, state_id):
    response = client.get(
        "/findings",
        params={"product_market_state_id": state_id},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def build_filler_requirement(client, writer, *, category, dimension, obligation_type,
                              statement, field, severity="MODERATE"):
    """
    Market Readiness attempts all eight canonical dimensions every run
    (RequirementDimension), not just the ones a category has
    distinctive content for - a dimension with zero active rules reads
    UNKNOWN, which forces G0 regardless of every other dimension's
    state. Each category below only has distinctive content for 3-4
    dimensions; this fills the rest with a minimal, uniform
    "administrative record on file" REQUIREMENT_RESULT check (flat
    single-subject shape) so a genuinely clean golden case can actually
    reach G3. Not meant to be interesting content on its own - every
    golden case just needs to supply `field` as present.
    """

    rv, rlv = build_requirement_and_rule(
        client, writer, category=category,
        requirement_overrides=dict(
            dimension=dimension, obligation_type=obligation_type,
            canonical_statement=statement, default_severity=severity, is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "exists", "field": field},
            output_type="REQUIREMENT_RESULT", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    return rv, rlv


def build_filler_document_requirement(client, writer, *, category, document_type, statement):
    """Same purpose as build_filler_requirement, for the DOCUMENTS
    dimension specifically - its checklist mechanism needs a
    document_type-keyed obligation_type and a `status` field check,
    not the flat shape."""

    rv, rlv = build_requirement_and_rule(
        client, writer, category=category,
        requirement_overrides=dict(
            dimension="DOCUMENTS", obligation_type=document_type,
            canonical_statement=statement, default_severity="MODERATE", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "exists", "field": "status"},
            output_type="REQUIREMENT_RESULT", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    return rv, rlv


# --- Category content builders ----------------------------------------------


def build_beauty_content(client, writer):
    """
    Beauty/personal care - the control case. Covers: CLAIMS (list-shaped
    subjects, `in` + `normalize`), LABEL (mandatory field, confidence
    gating), INGREDIENTS (list-shaped subjects reused generically -
    "claims" key is not Claims-specific, see the engine fix this
    corpus was proposed after), and an APPLICABILITY-only Requirement
    for a clean NOT_APPLICABLE case. Severities used: CRITICAL, MAJOR,
    MINOR - INFORMATIONAL/MODERATE come from the other two categories,
    so all five appear somewhere in the corpus.
    """

    requirement_versions: dict[str, dict] = {}
    rule_versions: dict[str, dict] = {}

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Beauty",
        requirement_overrides=dict(
            dimension="CLAIMS", obligation_type="PROHIBITED_THERAPEUTIC_CLAIM",
            canonical_statement="Cosmetic claims must not assert a therapeutic or medicinal effect.",
            default_severity="CRITICAL", is_hard_gate=True,
        ),
        rule_overrides=dict(
            condition={"op": "in", "field": "wording", "normalize": "lowercase",
                       "value": ["cures acne", "treats eczema"]},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["claims_prohibited"] = rv
    rule_versions["claims_prohibited"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Beauty",
        requirement_overrides=dict(
            dimension="LABEL", obligation_type="MANDATORY_NET_QUANTITY_DECLARATION",
            canonical_statement="Net quantity must be declared and legible on the primary panel.",
            default_severity="MAJOR", is_hard_gate=False,
        ),
        rule_overrides=dict(
            # not_equals (not exists) so low-confidence values are
            # actually gated - exists/not_exists ignore confidence entirely.
            condition={"op": "not_equals", "field": "extracted", "value": ""},
            output_type="REQUIREMENT_RESULT", unknown_behavior="FAIL_CLOSED",
        ),
    )
    requirement_versions["label_net_quantity"] = rv
    rule_versions["label_net_quantity"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Beauty",
        requirement_overrides=dict(
            dimension="LABEL", obligation_type="ALLERGEN_WARNING_STATEMENT",
            canonical_statement="Retail-packaged products must carry an allergen warning statement.",
            default_severity="MINOR", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "equals", "field": "product.packaging_type", "value": "retail"},
            output_type="APPLICABILITY", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["label_allergen_applicability"] = rv
    rule_versions["label_allergen_applicability"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Beauty",
        requirement_overrides=dict(
            dimension="INGREDIENTS", obligation_type="PROHIBITED_INGREDIENT",
            canonical_statement="Listed prohibited ingredients must not be present in the formula.",
            default_severity="CRITICAL", is_hard_gate=True,
        ),
        rule_overrides=dict(
            condition={"op": "in", "field": "ingredient_name", "normalize": "lowercase",
                       "value": ["mercury", "hydroquinone"]},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["ingredients_prohibited"] = rv
    rule_versions["ingredients_prohibited"] = rlv

    # Filler content - see build_filler_requirement docstring. Beauty
    # has distinctive content for CLAIMS/LABEL/INGREDIENTS only; the
    # other five canonical dimensions need SOMETHING active or every
    # golden case caps at G0 regardless of the dimensions that matter.
    rv, rlv = build_filler_requirement(
        client, writer, category="Beauty",
        dimension="CLASSIFICATION_ELIGIBILITY", obligation_type="COSMETIC_CATEGORY_CONFIRMED",
        statement="The product's cosmetic category classification must be confirmed and on file.",
        field="category_confirmed_ref",
    )
    requirement_versions["filler_classification"] = rv
    rule_versions["filler_classification"] = rlv

    rv, rlv = build_filler_document_requirement(
        client, writer, category="Beauty",
        document_type="product_safety_report",
        statement="A product safety report must be on file.",
    )
    requirement_versions["filler_documents"] = rv
    rule_versions["filler_documents"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Beauty",
        dimension="TESTING", obligation_type="STABILITY_TEST_ON_FILE",
        statement="A stability test reference must be on file.",
        field="stability_test_ref",
    )
    requirement_versions["filler_testing"] = rv
    rule_versions["filler_testing"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Beauty",
        dimension="REPRESENTATION", obligation_type="PACKAGING_ARTWORK_APPROVED",
        statement="Final packaging artwork must be approved and on file.",
        field="artwork_approved_ref",
    )
    requirement_versions["filler_representation"] = rv
    rule_versions["filler_representation"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Beauty",
        dimension="REGISTRATION_READINESS", obligation_type="RESPONSIBLE_PERSON_ON_FILE",
        statement="A designated responsible person reference must be on file.",
        field="responsible_person_ref",
    )
    requirement_versions["filler_registration"] = rv
    rule_versions["filler_registration"] = rlv

    release = create_active_release(
        client, writer, category=CATEGORY_BEAUTY,
        rule_version_ids=[v["id"] for v in rule_versions.values()],
        requirement_version_ids=[v["id"] for v in requirement_versions.values()],
    )

    return {"release": release, "requirement_versions": requirement_versions, "rule_versions": rule_versions}


def build_nutra_content(client, writer):
    """
    Nutraceuticals. Covers: INGREDIENTS as a FLAT single-subject fact
    set (the shape the engine fix in this session's prior ticket made
    reachable - plain numeric/string values, not a list) carrying THREE
    rules that each check a distinct field name on that one implicit
    subject (dosage soft limit, dosage hard ceiling, and an optional
    batch reference - REQUEST_INPUT coverage for this category), CLAIMS
    as an allowlist (`not_in`), LABEL reused for a "nutrition panel"
    (one field, mirroring Beauty's mandatory-field pattern - kept to one
    field deliberately, see module docstring), and an APPLICABILITY-only
    Requirement for NOT_APPLICABLE. Severities used: MAJOR, MODERATE,
    MINOR, INFORMATIONAL.
    """

    requirement_versions: dict[str, dict] = {}
    rule_versions: dict[str, dict] = {}

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Nutraceuticals",
        requirement_overrides=dict(
            dimension="INGREDIENTS", obligation_type="DAILY_DOSAGE_SOFT_LIMIT",
            canonical_statement="Daily dosage should not exceed the recommended soft limit.",
            default_severity="MAJOR", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "lte", "field": "daily_dosage_mg", "value": 1000},
            output_type="REQUIREMENT_RESULT", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["dosage_soft"] = rv
    rule_versions["dosage_soft"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Nutraceuticals",
        requirement_overrides=dict(
            dimension="INGREDIENTS", obligation_type="DAILY_DOSAGE_HARD_CEILING",
            canonical_statement="Daily dosage must not exceed the absolute safety ceiling.",
            default_severity="CRITICAL", is_hard_gate=True,
        ),
        rule_overrides=dict(
            condition={"op": "gt", "field": "daily_dosage_mg", "value": 2000},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["dosage_hard"] = rv
    rule_versions["dosage_hard"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Nutraceuticals",
        requirement_overrides=dict(
            dimension="INGREDIENTS", obligation_type="BATCH_REFERENCE_ON_FILE",
            canonical_statement="A batch reference should be on file where available.",
            default_severity="INFORMATIONAL", is_hard_gate=False,
        ),
        rule_overrides=dict(
            # Checks a distinct field name on the same flat implicit
            # subject as the dosage rules above - deliberately NOT a
            # second LABEL field (see module docstring: two field-
            # specific LABEL rules would cross-apply to each other's
            # subjects, since every active rule runs against every
            # submitted label_fields item, not just "its own"). A flat
            # dimension has exactly one implicit subject, so distinct
            # field names never cross-contaminate.
            condition={"op": "exists", "field": "batch_reference"},
            output_type="REQUIREMENT_RESULT", unknown_behavior="REQUEST_INPUT",
        ),
    )
    requirement_versions["batch_reference"] = rv
    rule_versions["batch_reference"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Nutraceuticals",
        requirement_overrides=dict(
            dimension="CLAIMS", obligation_type="PERMITTED_HEALTH_CLAIM_ONLY",
            canonical_statement="Health claims must use only pre-approved wording.",
            default_severity="MODERATE", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "not_in", "field": "wording", "normalize": "lowercase",
                       "value": ["supports normal energy metabolism", "contributes to normal immune function"]},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["health_claim"] = rv
    rule_versions["health_claim"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Nutraceuticals",
        requirement_overrides=dict(
            dimension="LABEL", obligation_type="NUTRITION_PANEL_SERVING_SIZE",
            canonical_statement="The nutrition panel must declare serving size.",
            default_severity="MAJOR", is_hard_gate=False,
        ),
        rule_overrides=dict(
            # not_equals (not exists) so low-confidence values are
            # actually gated - exists/not_exists ignore confidence entirely.
            condition={"op": "not_equals", "field": "extracted", "value": ""},
            output_type="REQUIREMENT_RESULT", unknown_behavior="FAIL_CLOSED",
        ),
    )
    requirement_versions["panel_serving_size"] = rv
    rule_versions["panel_serving_size"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Nutraceuticals",
        requirement_overrides=dict(
            dimension="LABEL", obligation_type="NUTRITION_PANEL_APPLICABILITY",
            canonical_statement="A nutrition panel is required for products intended for oral ingestion.",
            default_severity="INFORMATIONAL", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "equals", "field": "product.intended_use", "value": "oral"},
            output_type="APPLICABILITY", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["panel_applicability"] = rv
    rule_versions["panel_applicability"] = rlv

    # Filler content - see build_filler_requirement docstring.
    rv, rlv = build_filler_requirement(
        client, writer, category="Nutraceuticals",
        dimension="CLASSIFICATION_ELIGIBILITY", obligation_type="NUTRACEUTICAL_CATEGORY_CONFIRMED",
        statement="The product's nutraceutical category classification must be confirmed and on file.",
        field="category_confirmed_ref",
    )
    requirement_versions["filler_classification"] = rv
    rule_versions["filler_classification"] = rlv

    rv, rlv = build_filler_document_requirement(
        client, writer, category="Nutraceuticals",
        document_type="product_safety_report",
        statement="A product safety report must be on file.",
    )
    requirement_versions["filler_documents"] = rv
    rule_versions["filler_documents"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Nutraceuticals",
        dimension="TESTING", obligation_type="STABILITY_TEST_ON_FILE",
        statement="A stability test reference must be on file.",
        field="stability_test_ref",
    )
    requirement_versions["filler_testing"] = rv
    rule_versions["filler_testing"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Nutraceuticals",
        dimension="REPRESENTATION", obligation_type="PACKAGING_ARTWORK_APPROVED",
        statement="Final packaging artwork must be approved and on file.",
        field="artwork_approved_ref",
    )
    requirement_versions["filler_representation"] = rv
    rule_versions["filler_representation"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Nutraceuticals",
        dimension="REGISTRATION_READINESS", obligation_type="RESPONSIBLE_PERSON_ON_FILE",
        statement="A designated responsible person reference must be on file.",
        field="responsible_person_ref",
    )
    requirement_versions["filler_registration"] = rv
    rule_versions["filler_registration"] = rlv

    release = create_active_release(
        client, writer, category=CATEGORY_NUTRA,
        rule_version_ids=[v["id"] for v in rule_versions.values()],
        requirement_version_ids=[v["id"] for v in requirement_versions.values()],
    )

    return {"release": release, "requirement_versions": requirement_versions, "rule_versions": rule_versions}


def build_meddevice_content(client, writer):
    """
    Medical devices - the centerpiece. device_risk_class is a caller-
    supplied, confidence-wrapped fact (classification itself cannot be
    computed by this engine - CALCULATION_COMPONENT is stubbed, see
    README). Every Class-III-conditional Requirement is modeled as
    FINDING_PROPOSAL, deliberately never REQUIREMENT_RESULT - wrapping
    a gate in `all()` makes a REQUIREMENT_RESULT rule read NOT_SATISFIED
    (not "doesn't apply") for the wrong class, since a failed `all()`
    child always resolves a definite NO_MATCH. FINDING_PROPOSAL's
    NO_MATCH is always a silent no-op regardless of why it happened, so
    it's the only output_type here safe to gate this way alongside
    APPLICABILITY. See README for the full pathway-fit writeup - this is
    the concrete answer to whether classification-driven pathway fits
    or strains the model.
    """

    requirement_versions: dict[str, dict] = {}
    rule_versions: dict[str, dict] = {}

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Medical Devices",
        requirement_overrides=dict(
            dimension="CLASSIFICATION_ELIGIBILITY", obligation_type="RISK_CLASS_III_ELIGIBILITY",
            canonical_statement="Class III conformity requirements apply when the device is classified Risk Class III.",
            default_severity="MODERATE", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "equals", "field": "product.device_risk_class", "value": "III"},
            output_type="APPLICABILITY", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["classification_iii"] = rv
    rule_versions["classification_iii"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Medical Devices",
        requirement_overrides=dict(
            dimension="DOCUMENTS", obligation_type="clinical_evidence_report",
            canonical_statement="Class III devices must have a clinical evidence report on file.",
            default_severity="CRITICAL", is_hard_gate=True,
        ),
        rule_overrides=dict(
            condition={"op": "all", "conditions": [
                {"op": "equals", "field": "product.device_risk_class", "value": "III"},
                {"op": "not_exists", "field": "status"},
            ]},
            output_type="FINDING_PROPOSAL", unknown_behavior="FAIL_CLOSED",
        ),
    )
    requirement_versions["clinical_evidence"] = rv
    rule_versions["clinical_evidence"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Medical Devices",
        requirement_overrides=dict(
            dimension="TESTING", obligation_type="BENCH_TEST_REPORT",
            canonical_statement="Class III devices must have a bench test report reference on file.",
            default_severity="MAJOR", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "all", "conditions": [
                {"op": "equals", "field": "product.device_risk_class", "value": "III"},
                {"op": "not_exists", "field": "bench_test_report_ref"},
            ]},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["bench_test"] = rv
    rule_versions["bench_test"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Medical Devices",
        requirement_overrides=dict(
            dimension="REGISTRATION_READINESS", obligation_type="NOTIFIED_BODY_SIGNOFF",
            canonical_statement="Class III devices must have notified-body sign-off on file.",
            default_severity="MODERATE", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "all", "conditions": [
                {"op": "equals", "field": "product.device_risk_class", "value": "III"},
                {"op": "not_exists", "field": "notified_body_signoff_ref"},
            ]},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["notified_body"] = rv
    rule_versions["notified_body"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Medical Devices",
        requirement_overrides=dict(
            dimension="REGISTRATION_READINESS", obligation_type="SELF_DECLARATION_ON_FILE",
            canonical_statement="Class I devices must have a self-declaration on file.",
            default_severity="MINOR", is_hard_gate=False,
        ),
        rule_overrides=dict(
            condition={"op": "all", "conditions": [
                {"op": "equals", "field": "product.device_risk_class", "value": "I"},
                {"op": "not_exists", "field": "self_declaration_ref"},
            ]},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["self_declaration"] = rv
    rule_versions["self_declaration"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Medical Devices",
        requirement_overrides=dict(
            dimension="DOCUMENTS", obligation_type="model_name_consistency",
            canonical_statement="The device model name must be consistent across submitted documents.",
            default_severity="MAJOR", is_hard_gate=False,
            subject_kind="CONSISTENCY_CHECK",
        ),
        rule_overrides=dict(
            condition={"op": "equals", "field": "outcome", "value": "MISMATCH"},
            output_type="FINDING_PROPOSAL", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["model_name_consistency"] = rv
    rule_versions["model_name_consistency"] = rlv

    # Filler content - see build_filler_requirement docstring. Medical
    # devices has distinctive content for CLASSIFICATION_ELIGIBILITY/
    # DOCUMENTS/TESTING/REGISTRATION_READINESS; the other four need
    # something active. LABEL can't use the flat filler helper (LABEL
    # always uses the label_fields[] shape), so it's built directly.
    rv, rlv = build_filler_requirement(
        client, writer, category="Medical Devices",
        dimension="INGREDIENTS", obligation_type="BIOCOMPATIBLE_MATERIALS_ON_FILE",
        statement="A biocompatible-materials declaration reference must be on file.",
        field="materials_ref",
    )
    requirement_versions["filler_ingredients"] = rv
    rule_versions["filler_ingredients"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Medical Devices",
        dimension="CLAIMS", obligation_type="PERFORMANCE_CLAIM_REVIEWED",
        statement="Performance claims must have a substantiation review reference on file.",
        field="performance_claim_review_ref",
    )
    requirement_versions["filler_claims"] = rv
    rule_versions["filler_claims"] = rlv

    rv, rlv = build_requirement_and_rule(
        client, writer, category="Medical Devices",
        requirement_overrides=dict(
            dimension="LABEL", obligation_type="DEVICE_LABEL_UDI_PRESENT",
            canonical_statement="The device label must carry a Unique Device Identifier.",
            default_severity="MODERATE", is_hard_gate=False,
        ),
        rule_overrides=dict(
            # not_equals (not exists) so low-confidence values are
            # actually gated - exists/not_exists ignore confidence entirely.
            condition={"op": "not_equals", "field": "extracted", "value": ""},
            output_type="REQUIREMENT_RESULT", unknown_behavior="HUMAN_REVIEW",
        ),
    )
    requirement_versions["filler_label"] = rv
    rule_versions["filler_label"] = rlv

    rv, rlv = build_filler_requirement(
        client, writer, category="Medical Devices",
        dimension="REPRESENTATION", obligation_type="INSTRUCTIONS_FOR_USE_ON_FILE",
        statement="Instructions for use must be on file.",
        field="instructions_for_use_ref",
    )
    requirement_versions["filler_representation"] = rv
    rule_versions["filler_representation"] = rlv

    release = create_active_release(
        client, writer, category=CATEGORY_MEDDEVICE,
        rule_version_ids=[v["id"] for v in rule_versions.values()],
        requirement_version_ids=[v["id"] for v in requirement_versions.values()],
    )

    return {"release": release, "requirement_versions": requirement_versions, "rule_versions": rule_versions}


# --- Golden-case input_facts builders ----------------------------------------
#
# Shared between tests/test_testland_corpus.py (which asserts the exact
# outcome each shape produces) and scripts/seed_testland_corpus.py
# (which uses them to seed real, distinctly-stated demo runs for the
# baseline dashboard - see CLAUDE.md "TESTLAND corpus"). Single source
# of truth rather than duplicating the facts shapes in both places.


def beauty_filler_facts():
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


def beauty_facts(*, wording, packaging_type="retail", net_quantity_confidence=0.95):
    return {
        "CLAIMS": {"product": {}, "claims": [{"claim_id": "c1", "wording": wording}]},
        "LABEL": {"product": {"packaging_type": packaging_type},
                  "label_fields": [{"field_key": "net_quantity", "value": "50 mL",
                                     "confidence": net_quantity_confidence}]},
        "INGREDIENTS": {"product": {}, "claims": [{"claim_id": "ing-1", "ingredient_name": "Aqua"}]},
        **beauty_filler_facts(),
    }


def nutra_filler_facts():
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


def nutra_facts(*, dosage_mg, wording, serving_size_confidence=0.9, intended_use="oral", batch_reference="BATCH-1"):
    return {
        "INGREDIENTS": {"product": {}, "daily_dosage_mg": dosage_mg, "batch_reference": batch_reference},
        "CLAIMS": {"product": {}, "claims": [{"claim_id": "c1", "wording": wording}]},
        "LABEL": {"product": {"intended_use": intended_use},
                  "label_fields": [{"field_key": "serving_size", "value": "1 capsule",
                                     "confidence": serving_size_confidence}]},
        **nutra_filler_facts(),
    }


def meddevice_filler_facts():
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


def meddevice_facts(*, risk_class, confidence, documents=None, consistency_checks=None,
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
        **meddevice_filler_facts(),
    }
