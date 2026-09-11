from __future__ import annotations

import pytest

from app.core.dependencies import get_document_storage, get_query_classifier
from app.main import app
from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.organization.models import Organization
from app.modules.role.models import Role
from app.modules.user.models import User
from app.query_classification import (
    AskRegnovaQuestionClass,
    ClassificationResult,
    GeminiQueryClassifier,
    QueryClassifier,
)
from app.storage import LocalFilesystemStorage


@pytest.fixture()
def storage(tmp_path):
    backend = LocalFilesystemStorage(tmp_path)
    app.dependency_overrides[get_document_storage] = lambda: backend
    yield backend
    app.dependency_overrides.pop(get_document_storage, None)


class _FakeClassifier(QueryClassifier):
    """
    A test-controllable QueryClassifier, installed via
    app.dependency_overrides the same way the semantic/extraction
    slices' own fakes override their respective dependencies. Tests that
    don't install one get the real default (StubQueryClassifier, always
    UNSUPPORTED at confidence 0).
    """

    def __init__(self, canned=None, unavailable_reason=None):
        self.canned = canned or {}
        self.unavailable_reason = unavailable_reason
        self.calls = []

    def classify(self, *, question):
        self.calls.append(question)
        if self.unavailable_reason:
            from app.query_classification import QueryClassificationUnavailable
            raise QueryClassificationUnavailable(self.unavailable_reason, "simulated")
        if question in self.canned:
            return self.canned[question]
        return ClassificationResult(
            question_class=AskRegnovaQuestionClass.UNSUPPORTED.value,
            intent="", params={}, confidence=0.0,
            model_identifier="fake", prompt_version="fake-vTEST", reasoning="no canned answer",
        )


@pytest.fixture()
def classifier_override():
    def _install(classifier):
        app.dependency_overrides[get_query_classifier] = lambda: classifier
        return classifier

    yield _install
    app.dependency_overrides.pop(get_query_classifier, None)


def _result(question_class, intent="", params=None, confidence=0.9):
    return ClassificationResult(
        question_class=question_class, intent=intent, params=params or {},
        confidence=confidence, model_identifier="fake", prompt_version="fake-vTEST",
        reasoning="canned",
    )


def _ask(client, tenant, question, headers=None):
    return client.post("/ask", json={"question": question}, headers=headers or tenant["headers"])


def _employee_headers(db, tenant, email="employee-ask@example.com"):
    role = Role(organization_id=tenant["organization"].id, code="EMPLOYEE", name="Employee")
    db.add(role)
    db.flush()

    user = User(
        organization_id=tenant["organization"].id,
        role_id=role.id,
        first_name="Rank",
        last_name="File",
        email=email,
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


# --- Portfolio/regulatory-graph/state-explanation setup -----------------


def _create_product(client, tenant, name="Widget"):
    response = client.post("/products", json={"name": name}, headers=tenant["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _create_version(client, tenant, product_id, version="1.0.0", category="Claims"):
    response = client.post(
        f"/products/{product_id}/versions",
        json={"version": version, "category": category},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _publish_version(client, tenant, product_id, version_id):
    response = client.post(f"/products/{product_id}/versions/{version_id}/publish", headers=tenant["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _create_state(client, tenant, product_id, product_version_id, market="Malaysia"):
    response = client.post(
        f"/products/{product_id}/market-states",
        json={"product_version_id": product_version_id, "market": market, "jurisdiction": market},
        headers=tenant["headers"],
    )
    assert response.status_code == 200, response.text
    return response.json()


def _submit_verify_activate(client, writer, path):
    assert client.post(f"{path}/submit-for-review", headers=writer["headers"]).status_code == 200
    assert client.post(f"{path}/verify", json={"rationale": "verified"}, headers=writer["headers"]).status_code == 200
    response = client.post(f"{path}/activate", json={"rationale": "activated"}, headers=writer["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def _setup_finding_and_snapshot(client, tenant, writer, market="Malaysia"):
    """
    One CLAIMS requirement/rule that ALWAYS proposes a Finding, with a
    real source citation - published product version, active release,
    state, one market-readiness run. Returns
    (requirement_version, finding, state, snapshot).
    """
    source = client.post("/sources", headers=writer["headers"]).json()
    source_version = client.post(
        f"/sources/{source['id']}/versions",
        json={
            "title": "Test Source", "issuing_authority": "Test Authority",
            "jurisdiction": market, "tier": 1, "source_type": "OFFICIAL_GUIDELINE",
        },
        headers=writer["headers"],
    ).json()
    activated_source = _submit_verify_activate(
        client, writer, f"/sources/{source['id']}/versions/{source_version['id']}",
    )
    location = client.post(
        "/source-locations",
        json={"source_version_id": activated_source["id"], "section": "5", "normalized_text": "Claims must not be therapeutic."},
        headers=writer["headers"],
    ).json()

    requirement = client.post("/requirements", json={}, headers=writer["headers"]).json()
    requirement_version = client.post(
        f"/requirements/{requirement['id']}/versions",
        json={
            "jurisdiction": market, "market": market, "authority": "NPRA",
            "category": "Claims", "dimension": "CLAIMS",
            "obligation_type": "PROHIBITED_THERAPEUTIC_CLAIM",
            "canonical_statement": "Claims must not assert a therapeutic effect.",
            "default_severity": "MAJOR", "is_hard_gate": True,
            "authority_interpretation_label": "AUTHORITY_REQUIREMENT",
            "source_location_ids": [location["id"]],
        },
        headers=writer["headers"],
    ).json()
    requirement_version = _submit_verify_activate(
        client, writer, f"/requirements/{requirement['id']}/versions/{requirement_version['id']}",
    )

    rule = client.post("/rules", json={}, headers=writer["headers"]).json()
    rule_version = client.post(
        f"/rules/{rule['id']}/versions",
        json={
            "requirement_version_id": requirement_version["id"],
            "condition": {"op": "exists", "field": "wording"},
            "output_type": "FINDING_PROPOSAL", "unknown_behavior": "HUMAN_REVIEW",
        },
        headers=writer["headers"],
    ).json()
    rule_version = _submit_verify_activate(
        client, writer, f"/rules/{rule['id']}/versions/{rule_version['id']}",
    )

    response = client.post(
        "/regulatory-basis-releases",
        json={
            "jurisdiction": market, "market": market, "category": "Claims",
            "source_version_ids": [activated_source["id"]],
            "requirement_version_ids": [requirement_version["id"]],
            "rule_version_ids": [rule_version["id"]],
        },
        headers=writer["headers"],
    )
    assert response.status_code == 200, response.text

    product = _create_product(client, tenant)
    version = _create_version(client, tenant, product["id"])
    _publish_version(client, tenant, product["id"], version["id"])
    state = _create_state(client, tenant, product["id"], version["id"], market=market)

    run_response = client.post(
        "/market-readiness-runs",
        json={
            "product_market_state_id": state["id"],
            "input_facts": {"CLAIMS": {"product": {}, "claims": [{"claim_id": "c1", "wording": "clinically proven"}]}},
        },
        headers=tenant["headers"],
    )
    assert run_response.status_code == 200, run_response.text
    snapshot = run_response.json()

    findings = client.get(
        "/findings", params={"product_market_state_id": state["id"]}, headers=tenant["headers"],
    ).json()
    assert len(findings) == 1

    return requirement_version, findings[0], state, snapshot


# --- Basic classification/degradation ------------------------------------


def test_default_stub_classifier_is_unsupported(client, tenant_a):
    response = _ask(client, tenant_a, "what's your favorite color?")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question_class"] == "UNSUPPORTED"
    assert body["degraded"] is True
    assert body["degraded_reason"] == "unsupported"
    assert body["structured_result"] is None


def test_empty_question_rejected(client, tenant_a):
    response = client.post("/ask", json={"question": "   "}, headers=tenant_a["headers"])
    assert response.status_code == 400


def test_low_confidence_classification_does_not_dispatch(client, tenant_a, classifier_override):
    fake = classifier_override(_FakeClassifier(canned={
        "vague question": _result(AskRegnovaQuestionClass.STRUCTURED_PORTFOLIO.value, "PRODUCTS_BY_GATE", confidence=0.2),
    }))
    response = _ask(client, tenant_a, "vague question")
    body = response.json()
    assert body["degraded"] is True
    assert body["degraded_reason"] == "low_confidence"
    assert body["structured_result"] is None
    # The classification itself is still recorded, not discarded.
    assert body["question_class"] == "STRUCTURED_PORTFOLIO"
    assert body["confidence"] == 0.2


def test_classifier_unavailable_degrades_honestly(client, tenant_a, classifier_override):
    classifier_override(_FakeClassifier(unavailable_reason="timeout"))
    response = _ask(client, tenant_a, "how many products are blocked?")
    body = response.json()
    assert body["degraded"] is True
    assert body["degraded_reason"] == "timeout"  # exc.reason, verbatim - see service.py
    assert "temporarily unavailable" in body["narrative"]


@pytest.mark.parametrize("question_class", ["SEMANTIC_DOCUMENT_SEARCH", "WORKFLOW_COMMANDS"])
def test_deferred_classes_are_distinguishable_from_unsupported(client, tenant_a, classifier_override, question_class):
    classifier_override(_FakeClassifier(canned={
        "q": _result(question_class, confidence=0.9),
    }))
    response = _ask(client, tenant_a, "q")
    body = response.json()
    assert body["degraded"] is True
    assert body["degraded_reason"] == "not_yet_supported"
    assert "isn't supported yet" in body["narrative"]


# --- Structured portfolio -------------------------------------------------


def test_products_by_gate(client, db, tenant_a, storage, classifier_override):
    product = _create_product(client, tenant_a)
    version = _create_version(client, tenant_a, product["id"])
    _publish_version(client, tenant_a, product["id"], version["id"])
    _create_state(client, tenant_a, product["id"], version["id"])

    classifier_override(_FakeClassifier(canned={
        "how many products are blocked?": _result(
            AskRegnovaQuestionClass.STRUCTURED_PORTFOLIO.value, "PRODUCTS_BY_GATE", {"gate": "G0"},
        ),
    }))
    response = _ask(client, tenant_a, "how many products are blocked?")
    body = response.json()
    assert body["degraded"] is False
    assert body["structured_result"]["count"] == 1
    assert body["structured_result"]["gate"] == "G0"


def test_products_by_gate_requires_manager_tier(client, db, tenant_a, storage, classifier_override):
    classifier_override(_FakeClassifier(canned={
        "q": _result(AskRegnovaQuestionClass.STRUCTURED_PORTFOLIO.value, "PRODUCTS_BY_GATE", {}),
    }))
    employee_headers = _employee_headers(db, tenant_a)
    response = _ask(client, tenant_a, "q", headers=employee_headers)
    assert response.status_code == 403


def test_documents_expiring_within(client, tenant_a, storage, classifier_override):
    document = client.post("/documents", json={"document_type": "GMP_CERTIFICATE"}, headers=tenant_a["headers"]).json()
    files = {"file": ("cert.pdf", b"%PDF-1.4\n%mock\n%%EOF", "application/pdf")}
    version = client.post(f"/documents/{document['id']}/versions", files=files, headers=tenant_a["headers"]).json()
    client.put(
        f"/documents/{document['id']}/versions/{version['id']}/fields/expiry_date",
        json={"value": "2025-01-01"}, headers=tenant_a["headers"],
    )
    client.post(f"/documents/{document['id']}/versions/{version['id']}/verify", json={}, headers=tenant_a["headers"])

    classifier_override(_FakeClassifier(canned={
        "what expires in 90 days?": _result(
            AskRegnovaQuestionClass.STRUCTURED_PORTFOLIO.value, "DOCUMENTS_EXPIRING_WITHIN", {"within_days": "36500"},
        ),
    }))
    response = _ask(client, tenant_a, "what expires in 90 days?")
    body = response.json()
    assert body["degraded"] is False
    assert body["structured_result"]["count"] == 1
    assert body["structured_result"]["documents"][0]["document_version_id"] == version["id"]


# --- Regulatory graph -------------------------------------------------


def test_requirement_detail_reachable_by_employee(client, db, tenant_a, regulatory_content_writer, classifier_override):
    requirement_version, _finding, _state, _snapshot = _setup_finding_and_snapshot(client, tenant_a, regulatory_content_writer)

    classifier_override(_FakeClassifier(canned={
        "what does this require?": _result(
            AskRegnovaQuestionClass.REGULATORY_GRAPH.value, "REQUIREMENT_DETAIL",
            {"requirement_version_id": requirement_version["id"]},
        ),
    }))
    employee_headers = _employee_headers(db, tenant_a)
    response = _ask(client, tenant_a, "what does this require?", headers=employee_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is False
    assert body["structured_result"]["authority_interpretation_label"] == "AUTHORITY_REQUIREMENT"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["normalized_text"] == "Claims must not be therapeutic."
    assert body["sources"][0]["source_title"] == "Test Source"


def test_requirement_detail_unknown_id_degrades_cleanly(client, tenant_a, classifier_override):
    classifier_override(_FakeClassifier(canned={
        "q": _result(
            AskRegnovaQuestionClass.REGULATORY_GRAPH.value, "REQUIREMENT_DETAIL",
            {"requirement_version_id": "11111111-1111-1111-1111-111111111111"},
        ),
    }))
    response = _ask(client, tenant_a, "q")
    body = response.json()
    assert body["degraded"] is False  # a real, honest "not found" answer, not a system failure
    assert body["structured_result"]["found"] is False


# --- State explanation -------------------------------------------------


def test_explain_gate_and_finding(client, db, tenant_a, regulatory_content_writer, classifier_override):
    requirement_version, finding, state, _snapshot = _setup_finding_and_snapshot(client, tenant_a, regulatory_content_writer)

    classifier_override(_FakeClassifier(canned={
        "why is this blocked?": _result(
            AskRegnovaQuestionClass.STATE_EXPLANATION.value, "EXPLAIN_GATE",
            {"product_market_state_id": state["id"]},
        ),
    }))
    response = _ask(client, tenant_a, "why is this blocked?")
    body = response.json()
    assert body["degraded"] is False
    # Only CLAIMS has real rule content in this minimal setup, so the
    # other 7 dimensions settle UNKNOWN and G0 (worse than G1) wins on
    # worst-first precedence - the specific gate value isn't the point
    # here, only that EXPLAIN_GATE surfaces the REAL current gate/reasons.
    assert body["structured_result"]["overall_gate"].startswith("G")
    assert len(body["structured_result"]["readiness_reason_codes"]) > 0
    assert body["structured_result"]["dimension_summary"]["CLAIMS"]["state"] == "NON_COMPLIANT"

    classifier_override(_FakeClassifier(canned={
        "why is this finding open?": _result(
            AskRegnovaQuestionClass.STATE_EXPLANATION.value, "EXPLAIN_FINDING",
            {"finding_id": finding["id"]},
        ),
    }))
    response = _ask(client, tenant_a, "why is this finding open?")
    body = response.json()
    assert body["degraded"] is False
    assert body["structured_result"]["requirement"]["requirement_version_id"] == requirement_version["id"]
    assert body["structured_result"]["rule"] is not None
    assert len(body["sources"]) == 1


def test_explain_finding_cross_org_is_not_found_not_leaked(client, db, tenant_a, tenant_b, regulatory_content_writer, classifier_override):
    _rv, finding, _state, _snapshot = _setup_finding_and_snapshot(client, tenant_a, regulatory_content_writer)

    classifier_override(_FakeClassifier(canned={
        "q": _result(
            AskRegnovaQuestionClass.STATE_EXPLANATION.value, "EXPLAIN_FINDING",
            {"finding_id": finding["id"]},
        ),
    }))
    response = _ask(client, tenant_b, "q")
    body = response.json()
    assert body["degraded"] is False
    assert body["structured_result"]["found"] is False  # never tenant_a's real finding data


def test_explain_gate_requires_manager_tier(client, db, tenant_a, classifier_override):
    classifier_override(_FakeClassifier(canned={
        "q": _result(AskRegnovaQuestionClass.STATE_EXPLANATION.value, "EXPLAIN_GATE", {"product_market_state_id": "x"}),
    }))
    employee_headers = _employee_headers(db, tenant_a)
    response = _ask(client, tenant_a, "q", headers=employee_headers)
    assert response.status_code == 403


# --- History -------------------------------------------------------------


def test_ask_history_is_recorded_and_listable(client, tenant_a, classifier_override):
    classifier_override(_FakeClassifier())
    _ask(client, tenant_a, "first question")
    _ask(client, tenant_a, "second question")

    response = client.get("/ask", headers=tenant_a["headers"])
    assert response.status_code == 200
    questions = {q["question"] for q in response.json()}
    assert questions == {"first question", "second question"}


def test_ask_history_isolated_across_organizations(client, tenant_a, tenant_b, classifier_override):
    classifier_override(_FakeClassifier())
    _ask(client, tenant_a, "tenant a's question")

    response = client.get("/ask", headers=tenant_b["headers"])
    assert response.json() == []


# --- Organization.is_synthetic gate (CLAUDE.md "Ask RegNova") -------------


def test_gemini_classifier_blocked_for_non_synthetic_organization(client, db, tenant_a):
    """
    A REAL GeminiQueryClassifier (bogus key, synthetic_data_ack=True) is
    installed directly - if the Organization.is_synthetic guard did NOT
    fire first, classify() itself would attempt a real HTTP call and
    fail with "http_error" (or "not_configured" if ack were False). The
    guard must fire BEFORE that, producing "organization_not_synthetic"
    specifically - proving the check runs against the organization, not
    just against whether a key happens to be configured.
    """
    org = db.get(Organization, tenant_a["organization"].id)
    assert org.is_synthetic is False  # the default - confirms the premise

    real_classifier = GeminiQueryClassifier(
        api_key="not-a-real-key", model="gemini-3.6-flash",
        timeout_seconds=1.0, synthetic_data_ack=True,
    )
    app.dependency_overrides[get_query_classifier] = lambda: real_classifier
    try:
        response = _ask(client, tenant_a, "how many products are blocked?")
    finally:
        app.dependency_overrides.pop(get_query_classifier, None)

    body = response.json()
    assert body["degraded"] is True
    assert body["degraded_reason"] == "organization_not_synthetic"
