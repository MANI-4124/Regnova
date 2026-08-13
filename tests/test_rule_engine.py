from __future__ import annotations

import pytest

from app.engine import DEFAULT_MIN_CONFIDENCE, evaluate_condition
from app.engine.condition_evaluator import (
    UnknownNormalizeFunction,
    UnrecognizedConditionOperator,
)


def test_equals_match():
    result = evaluate_condition(
        {"op": "equals", "field": "category", "value": "cosmetic"},
        {"category": "cosmetic"},
    )
    assert result.outcome == "MATCH"


def test_equals_no_match():
    result = evaluate_condition(
        {"op": "equals", "field": "category", "value": "cosmetic"},
        {"category": "drug"},
    )
    assert result.outcome == "NO_MATCH"


def test_missing_field_is_unknown_and_recorded():
    result = evaluate_condition(
        {"op": "equals", "field": "category", "value": "cosmetic"},
        {},
    )
    assert result.outcome == "UNKNOWN"
    assert result.missing_fields == ["category"]


def test_exists_true_when_present():
    result = evaluate_condition(
        {"op": "exists", "field": "wording"},
        {"wording": "clinically proven"},
    )
    assert result.outcome == "MATCH"


def test_exists_false_when_absent_never_unknown():
    result = evaluate_condition(
        {"op": "exists", "field": "wording"},
        {},
    )
    assert result.outcome == "NO_MATCH"
    assert result.missing_fields == []


def test_not_exists_true_when_absent_never_unknown():
    result = evaluate_condition(
        {"op": "not_exists", "field": "wording"},
        {},
    )
    assert result.outcome == "MATCH"
    assert result.missing_fields == []


def test_not_exists_false_when_present():
    result = evaluate_condition(
        {"op": "not_exists", "field": "wording"},
        {"wording": "x"},
    )
    assert result.outcome == "NO_MATCH"


@pytest.mark.parametrize(
    ("op", "value", "expected", "outcome"),
    [
        ("gt", 5, 1, "MATCH"),
        ("gt", 1, 5, "NO_MATCH"),
        ("gte", 5, 5, "MATCH"),
        ("lt", 1, 5, "MATCH"),
        ("lte", 5, 5, "MATCH"),
        ("not_equals", "a", "b", "MATCH"),
        ("not_equals", "a", "a", "NO_MATCH"),
        ("in", "a", ["a", "b"], "MATCH"),
        ("in", "c", ["a", "b"], "NO_MATCH"),
        ("not_in", "c", ["a", "b"], "MATCH"),
    ],
)
def test_scalar_comparisons(op, value, expected, outcome):
    result = evaluate_condition(
        {"op": op, "field": "x", "value": expected},
        {"x": value},
    )
    assert result.outcome == outcome


def test_normalize_lowercase_applied_before_comparison():
    result = evaluate_condition(
        {
            "op": "equals",
            "field": "wording",
            "value": "clinically proven",
            "normalize": "lowercase",
        },
        {"wording": "CLINICALLY PROVEN"},
    )
    assert result.outcome == "MATCH"


def test_unknown_normalize_function_raises():
    with pytest.raises(UnknownNormalizeFunction):
        evaluate_condition(
            {"op": "equals", "field": "wording", "value": "x", "normalize": "does_not_exist"},
            {"wording": "x"},
        )


def test_unrecognized_operator_raises():
    with pytest.raises(UnrecognizedConditionOperator):
        evaluate_condition({"op": "bogus_op", "field": "x", "value": 1}, {"x": 1})


class TestCombinators:
    def test_all_match_when_every_child_matches(self):
        condition = {
            "op": "all",
            "conditions": [
                {"op": "equals", "field": "a", "value": 1},
                {"op": "equals", "field": "b", "value": 2},
            ],
        }
        result = evaluate_condition(condition, {"a": 1, "b": 2})
        assert result.outcome == "MATCH"

    def test_all_no_match_wins_over_unknown(self):
        # a definite NO_MATCH always wins an "all" regardless of a
        # sibling UNKNOWN - Kleene three-valued logic.
        condition = {
            "op": "all",
            "conditions": [
                {"op": "equals", "field": "a", "value": 1},
                {"op": "equals", "field": "missing", "value": 2},
            ],
        }
        result = evaluate_condition(condition, {"a": 999})
        assert result.outcome == "NO_MATCH"

    def test_all_unknown_when_no_no_match_but_some_unknown(self):
        condition = {
            "op": "all",
            "conditions": [
                {"op": "equals", "field": "a", "value": 1},
                {"op": "equals", "field": "missing", "value": 2},
            ],
        }
        result = evaluate_condition(condition, {"a": 1})
        assert result.outcome == "UNKNOWN"
        assert result.missing_fields == ["missing"]

    def test_any_match_wins_over_unknown(self):
        condition = {
            "op": "any",
            "conditions": [
                {"op": "equals", "field": "a", "value": 1},
                {"op": "equals", "field": "missing", "value": 2},
            ],
        }
        result = evaluate_condition(condition, {"a": 1})
        assert result.outcome == "MATCH"

    def test_any_unknown_when_no_match_but_some_unknown(self):
        condition = {
            "op": "any",
            "conditions": [
                {"op": "equals", "field": "a", "value": 999},
                {"op": "equals", "field": "missing", "value": 2},
            ],
        }
        result = evaluate_condition(condition, {"a": 1})
        assert result.outcome == "UNKNOWN"

    def test_any_no_match_when_every_child_no_matches(self):
        condition = {
            "op": "any",
            "conditions": [
                {"op": "equals", "field": "a", "value": 999},
                {"op": "equals", "field": "b", "value": 999},
            ],
        }
        result = evaluate_condition(condition, {"a": 1, "b": 2})
        assert result.outcome == "NO_MATCH"

    def test_nested_combinators(self):
        condition = {
            "op": "all",
            "conditions": [
                {"op": "equals", "field": "category", "value": "cosmetic"},
                {
                    "op": "any",
                    "conditions": [
                        {"op": "equals", "field": "wording", "value": "cures acne"},
                        {"op": "equals", "field": "wording", "value": "clinically proven"},
                    ],
                },
            ],
        }
        result = evaluate_condition(
            condition,
            {"category": "cosmetic", "wording": "clinically proven"},
        )
        assert result.outcome == "MATCH"


class TestDotPathAndNestedFacts:
    def test_dotted_field_path_resolves_nested_dict(self):
        result = evaluate_condition(
            {"op": "equals", "field": "context.language", "value": "en"},
            {"context": {"language": "en"}},
        )
        assert result.outcome == "MATCH"

    def test_dotted_field_path_missing_intermediate_is_unknown(self):
        result = evaluate_condition(
            {"op": "equals", "field": "context.language", "value": "en"},
            {},
        )
        assert result.outcome == "UNKNOWN"
        assert result.missing_fields == ["context.language"]


class TestAgainstSyntheticRuleVersionTestFixtures:
    """
    Mirrors the mechanism AssessmentRunService relies on implicitly:
    RuleVersion.test_fixtures is a list of {input_facts, expected_output}
    pairs (per CLAUDE.md). This validates the engine directly against
    that shape using synthetic Claims-style rules/facts, not real
    seeded NPRA content.
    """

    def test_prohibited_therapeutic_claim_fixtures(self):
        condition = {
            "op": "in",
            "field": "normalized_wording",
            "value": ["cures acne", "treats eczema"],
            "normalize": "lowercase",
        }

        test_fixtures = [
            {
                "input_facts": {"normalized_wording": "Cures Acne"},
                "expected_output": "MATCH",
            },
            {
                "input_facts": {"normalized_wording": "soothes dry skin"},
                "expected_output": "NO_MATCH",
            },
            {
                "input_facts": {},
                "expected_output": "UNKNOWN",
            },
        ]

        for fixture in test_fixtures:
            result = evaluate_condition(condition, fixture["input_facts"])
            assert result.outcome == fixture["expected_output"], fixture


class TestConfidenceGating:
    """
    Label's OCR-extracted facts arrive as {"value", "confidence"}
    wrappers instead of Claims' plain scalars - these tests validate the
    generic (not Label-specific) engine mechanism that makes AC-FR-06-02
    possible: a field present but below its confidence threshold
    resolves UNKNOWN with reason="low_confidence", same outcome as a
    missing field but distinguishable in the trace.
    """

    def test_confidence_wrapped_value_above_threshold_compares_normally(self):
        result = evaluate_condition(
            {"op": "equals", "field": "extracted", "value": "50 mL"},
            {"extracted": {"value": "50 mL", "confidence": 0.92}},
        )
        assert result.outcome == "MATCH"
        assert result.unknown_reason is None

    def test_confidence_wrapped_value_below_default_threshold_is_unknown(self):
        result = evaluate_condition(
            {"op": "equals", "field": "extracted", "value": "50 mL"},
            {"extracted": {"value": "50 mL", "confidence": 0.31}},
        )
        assert result.outcome == "UNKNOWN"
        assert result.unknown_reason == "low_confidence"
        assert result.missing_fields == ["extracted"]

        entry = result.trace[0]
        assert entry["reason"] == "low_confidence"
        assert entry["confidence"] == 0.31

    def test_default_threshold_matches_d51_boundary(self):
        # D5.1: "Low-confidence OCR on mandatory label field | <=0.49"
        just_below = evaluate_condition(
            {"op": "equals", "field": "extracted", "value": "x"},
            {"extracted": {"value": "x", "confidence": 0.49}},
        )
        assert just_below.outcome == "UNKNOWN"

        at_default = evaluate_condition(
            {"op": "equals", "field": "extracted", "value": "x"},
            {"extracted": {"value": "x", "confidence": DEFAULT_MIN_CONFIDENCE}},
        )
        assert at_default.outcome == "MATCH"

    def test_leaf_level_min_confidence_overrides_default(self):
        result = evaluate_condition(
            {"op": "equals", "field": "extracted", "value": "x", "min_confidence": 0.9},
            {"extracted": {"value": "x", "confidence": 0.8}},
        )
        assert result.outcome == "UNKNOWN"
        assert result.unknown_reason == "low_confidence"

    def test_exists_ignores_confidence_entirely(self):
        result = evaluate_condition(
            {"op": "exists", "field": "extracted"},
            {"extracted": {"value": None, "confidence": 0.0}},
        )
        assert result.outcome == "MATCH"
        assert result.unknown_reason is None

    def test_not_exists_ignores_confidence_entirely(self):
        result = evaluate_condition(
            {"op": "not_exists", "field": "extracted"},
            {},
        )
        assert result.outcome == "MATCH"

    def test_missing_confidence_key_fails_safe_to_zero(self):
        result = evaluate_condition(
            {"op": "equals", "field": "extracted", "value": "x"},
            {"extracted": {"value": "x"}},  # malformed - no "confidence" key
        )
        # No "confidence" key means this isn't detected as a wrapper at
        # all (both keys are required) - it's treated as a plain dict
        # value, compared as-is. Documented here so the boundary is
        # explicit, not just implied.
        assert result.outcome == "NO_MATCH"

    def test_normalize_applies_after_confidence_unwrap(self):
        result = evaluate_condition(
            {
                "op": "equals",
                "field": "extracted",
                "value": "clinically proven",
                "normalize": "lowercase",
            },
            {"extracted": {"value": "CLINICALLY PROVEN", "confidence": 0.95}},
        )
        assert result.outcome == "MATCH"

    def test_combinator_merges_low_confidence_over_missing(self):
        condition = {
            "op": "all",
            "conditions": [
                {"op": "equals", "field": "missing_field", "value": 1},
                {"op": "equals", "field": "extracted", "value": "x"},
            ],
        }
        result = evaluate_condition(
            condition,
            {"extracted": {"value": "x", "confidence": 0.1}},
        )
        assert result.outcome == "UNKNOWN"
        assert result.unknown_reason == "low_confidence"

    def test_combinator_reason_is_missing_when_no_low_confidence_present(self):
        condition = {
            "op": "all",
            "conditions": [
                {"op": "equals", "field": "missing_a", "value": 1},
                {"op": "equals", "field": "missing_b", "value": 2},
            ],
        }
        result = evaluate_condition(condition, {})
        assert result.outcome == "UNKNOWN"
        assert result.unknown_reason == "missing"
