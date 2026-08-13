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
# This is deliberately small, just enough for synthetic Claims fixtures;
# it is not the real registry the spec gestures at.
_NORMALIZERS = {
    "lowercase": lambda v: v.lower() if isinstance(v, str) else v,
    "strip": lambda v: v.strip() if isinstance(v, str) else v,
    "collapse_whitespace": lambda v: " ".join(v.split()) if isinstance(v, str) else v,
}

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
    """

    outcome: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)


def evaluate_condition(condition: dict[str, Any], facts: dict[str, Any]) -> EvaluationResult:
    """
    Walk a RuleVersion.condition tree (C6) against a flat facts dict and
    produce a three-valued result. Facts are always a single flat,
    scalar-valued subject - the engine never traverses arrays itself
    (see CLAUDE.md "Assessment engine" for why: callers iterate the
    subject collection - e.g. one claim at a time for Claims - and call
    this once per subject).
    """

    trace: list[dict[str, Any]] = []
    missing: list[str] = []
    outcome = _walk(condition, facts, trace, missing)
    return EvaluationResult(
        outcome=outcome,
        trace=trace,
        missing_fields=sorted(set(missing)),
    )


def _resolve_field(facts: dict[str, Any], path: str) -> Any:
    current: Any = facts
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _normalize(value: Any, fn_name: str | None) -> Any:
    if fn_name is None or value is _MISSING:
        return value

    normalizer = _NORMALIZERS.get(fn_name)
    if normalizer is None:
        raise UnknownNormalizeFunction(fn_name)

    return normalizer(value)


def _walk(node: dict[str, Any], facts: dict[str, Any], trace: list, missing: list) -> str:
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
) -> str:
    children = node.get("conditions", [])
    results = [_walk(child, facts, trace, missing) for child in children]

    # Standard Kleene three-valued logic - not spec-stated explicitly,
    # flagged as an inferred (if standard) semantic when this was
    # proposed. A definite NO_MATCH always wins an "all" regardless of
    # other UNKNOWNs; a definite MATCH always wins an "any".
    if op == "all":
        if "NO_MATCH" in results:
            return "NO_MATCH"
        if "UNKNOWN" in results:
            return "UNKNOWN"
        return "MATCH"

    if "MATCH" in results:
        return "MATCH"
    if "UNKNOWN" in results:
        return "UNKNOWN"
    return "NO_MATCH"


def _walk_leaf(
    op: str,
    node: dict[str, Any],
    facts: dict[str, Any],
    trace: list,
    missing: list,
) -> str:
    field_path = node.get("field")
    present = field_path is not None and _resolve_field(facts, field_path) is not _MISSING
    raw_value = _resolve_field(facts, field_path) if present else _MISSING
    value = _normalize(raw_value, node.get("normalize")) if present else _MISSING
    expected = node.get("value")

    # exists/not_exists test presence itself, so absence is never
    # "unknown" for them - it's the definite answer. Every other
    # operator needs the value to compare against, so absence there
    # really is unknown (never a default pass - C6).
    if op == "exists":
        outcome = "MATCH" if present else "NO_MATCH"
    elif op == "not_exists":
        outcome = "NO_MATCH" if present else "MATCH"
    elif not present:
        missing.append(field_path)
        outcome = "UNKNOWN"
    else:
        outcome = _apply_comparison(op, value, expected)

    trace.append(
        {
            "op": op,
            "field": field_path,
            "expected": expected,
            "actual": None if value is _MISSING else value,
            "outcome": outcome,
        },
    )

    return outcome


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
