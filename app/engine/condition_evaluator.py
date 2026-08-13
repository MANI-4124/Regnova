from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LEAF_OPS = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "exists",
    "not_exists",
}

COMBINATOR_OPS = {"all", "any"}

# Placeholder subset only - CLAUDE.md already flags that no registry of
# "approved normalization functions" exists anywhere in the spec (C6).
# This is deliberately small, just enough for synthetic fixtures; it is
# not the real registry the spec gestures at.
_NORMALIZERS = {
    "lowercase": lambda v: v.lower() if isinstance(v, str) else v,
    "strip": lambda v: v.strip() if isinstance(v, str) else v,
    "collapse_whitespace": lambda v: " ".join(v.split()) if isinstance(v, str) else v,
}

# Not a placeholder guess - D5.1's own hard-cap table gives this exact
# number ("Low-confidence OCR on mandatory label field | <=0.49 | RA
# visual check"), and Appendix 4 explicitly frames confidence-threshold
# ratification as a RegNova-owned decision that "this pack supplies
# defaults" for. Applies whenever a leaf resolves a confidence-wrapped
# value and the leaf itself doesn't override with its own min_confidence.
DEFAULT_MIN_CONFIDENCE = 0.5

_MISSING = object()


class UnknownNormalizeFunction(Exception):
    def __init__(self, fn_name: str):
        self.fn_name = fn_name
        super().__init__(f"Unknown normalize function: {fn_name!r}")


class UnrecognizedConditionOperator(Exception):
    def __init__(self, op: Any):
        self.op = op
        super().__init__(f"Unrecognized condition operator: {op!r}")


@dataclass
class EvaluationResult:
    """
    outcome is one of MATCH / NO_MATCH / UNKNOWN - three-valued (Kleene)
    logic, not a plain bool. trace/missing_fields exist to satisfy C10's
    "deterministic trace" metadata requirement for the Rule-evaluation
    lineage hop - callers should not need to re-derive why a result came
    out the way it did.

    unknown_reason distinguishes *why* the root came out UNKNOWN -
    "missing" (a referenced field was absent from facts) vs
    "low_confidence" (present but below its confidence threshold, e.g.
    OCR-extracted Label fields). Only set when outcome == "UNKNOWN".
    Callers (AssessmentRunService) hard-pin low_confidence to behave as
    HUMAN_REVIEW regardless of the rule's own unknown_behavior -
    AC-FR-06-02 requires low-confidence OCR never silently pass a
    mandatory check, which reads as a system invariant, not something a
    rule author's declared policy can override.
    """

    outcome: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    unknown_reason: str | None = None


def evaluate_condition(condition: dict[str, Any], facts: dict[str, Any]) -> EvaluationResult:
    """
    Walk a RuleVersion.condition tree (C6) against a flat facts dict and
    produce a three-valued result. Facts are always a single flat
    subject - the engine never traverses arrays itself (see CLAUDE.md
    "Assessment engine" for why: callers iterate the subject collection
    - one claim/label field at a time - and call this once per subject).

    A field's value in facts may be a plain scalar, or a
    {"value": ..., "confidence": ...} wrapper (both keys required) for
    extraction-derived facts like Label's OCR-read fields - Claims never
    uses the wrapper and is completely unaffected by it.
    """

    trace: list[dict[str, Any]] = []
    missing: list[str] = []
    outcome, reason = _walk(condition, facts, trace, missing)
    return EvaluationResult(
        outcome=outcome,
        trace=trace,
        missing_fields=sorted(set(missing)),
        unknown_reason=reason,
    )


def _resolve_field(facts: dict[str, Any], path: str) -> Any:
    current: Any = facts
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _is_confidence_wrapped(raw: Any) -> bool:
    return isinstance(raw, dict) and "value" in raw and "confidence" in raw


def _normalize(value: Any, fn_name: str | None) -> Any:
    if fn_name is None or value is _MISSING:
        return value

    normalizer = _NORMALIZERS.get(fn_name)
    if normalizer is None:
        raise UnknownNormalizeFunction(fn_name)

    return normalizer(value)


def _walk(
    node: dict[str, Any],
    facts: dict[str, Any],
    trace: list,
    missing: list,
) -> tuple[str, str | None]:
    op = node.get("op")

    if op in COMBINATOR_OPS:
        return _walk_combinator(op, node, facts, trace, missing)

    if op in LEAF_OPS:
        return _walk_leaf(op, node, facts, trace, missing)

    raise UnrecognizedConditionOperator(op)


def _walk_combinator(
    op: str,
    node: dict[str, Any],
    facts: dict[str, Any],
    trace: list,
    missing: list,
) -> tuple[str, str | None]:
    children = node.get("conditions", [])
    child_results = [_walk(child, facts, trace, missing) for child in children]
    outcomes = [outcome for outcome, _reason in child_results]
    reasons = [reason for _outcome, reason in child_results if reason is not None]

    # low_confidence wins the reason merge - same worst-first philosophy
    # as everywhere else in this design: if ANY contributing UNKNOWN was
    # confidence-gated, the combined reason is low_confidence (forcing
    # human review), even if siblings were merely missing.
    merged_reason = "low_confidence" if "low_confidence" in reasons else (reasons[0] if reasons else None)

    # Standard Kleene three-valued logic - not spec-stated explicitly,
    # flagged as an inferred (if standard) semantic when this was
    # proposed. A definite NO_MATCH always wins an "all" regardless of
    # other UNKNOWNs; a definite MATCH always wins an "any".
    if op == "all":
        if "NO_MATCH" in outcomes:
            return "NO_MATCH", None
        if "UNKNOWN" in outcomes:
            return "UNKNOWN", merged_reason
        return "MATCH", None

    if "MATCH" in outcomes:
        return "MATCH", None
    if "UNKNOWN" in outcomes:
        return "UNKNOWN", merged_reason
    return "NO_MATCH", None


def _walk_leaf(
    op: str,
    node: dict[str, Any],
    facts: dict[str, Any],
    trace: list,
    missing: list,
) -> tuple[str, str | None]:
    field_path = node.get("field")
    raw = _resolve_field(facts, field_path) if field_path else _MISSING
    present = raw is not _MISSING

    confidence: float | None = None
    value: Any = _MISSING

    if present:
        if _is_confidence_wrapped(raw):
            confidence = raw.get("confidence")
            if confidence is None:
                # Malformed input (has "value" but no real confidence) -
                # fail safe rather than silently treating it as trusted.
                confidence = 0.0
            value = raw.get("value")
        else:
            value = raw

    reason: str | None = None

    # exists/not_exists test presence itself, so absence (or low
    # confidence) is never "unknown" for them - the extraction attempt
    # happening at all, and whether the field is structurally there, is
    # the definite answer they care about, not whether that value can be
    # trusted enough to compare against something.
    if op == "exists":
        outcome = "MATCH" if present else "NO_MATCH"
    elif op == "not_exists":
        outcome = "NO_MATCH" if present else "MATCH"
    elif not present:
        missing.append(field_path)
        outcome = "UNKNOWN"
        reason = "missing"
    elif confidence is not None and confidence < node.get("min_confidence", DEFAULT_MIN_CONFIDENCE):
        missing.append(field_path)
        outcome = "UNKNOWN"
        reason = "low_confidence"
    else:
        value = _normalize(value, node.get("normalize"))
        outcome = _apply_comparison(op, value, node.get("value"))

    trace_entry: dict[str, Any] = {
        "op": op,
        "field": field_path,
        "expected": node.get("value"),
        "actual": None if value is _MISSING else value,
        "outcome": outcome,
    }
    if reason is not None:
        trace_entry["reason"] = reason
    if confidence is not None:
        trace_entry["confidence"] = confidence

    trace.append(trace_entry)

    return outcome, reason


def _apply_comparison(op: str, value: Any, expected: Any) -> str:
    if op == "equals":
        return "MATCH" if value == expected else "NO_MATCH"
    if op == "not_equals":
        return "MATCH" if value != expected else "NO_MATCH"
    if op == "in":
        return "MATCH" if value in expected else "NO_MATCH"
    if op == "not_in":
        return "MATCH" if value not in expected else "NO_MATCH"
    if op == "gt":
        return "MATCH" if value > expected else "NO_MATCH"
    if op == "gte":
        return "MATCH" if value >= expected else "NO_MATCH"
    if op == "lt":
        return "MATCH" if value < expected else "NO_MATCH"
    if op == "lte":
        return "MATCH" if value <= expected else "NO_MATCH"

    raise UnrecognizedConditionOperator(op)
