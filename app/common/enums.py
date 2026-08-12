from __future__ import annotations

from enum import Enum


class UnknownBehavior(str, Enum):
    """
    Shared cross-cutting policy for how a constrained declarative
    expression (a Requirement's applicability predicate, a Rule's
    condition) behaves when a required input is missing. Both C5 and C6
    describe this identically ("explicit fail-closed, request-input or
    human-review behavior; never default pass") - it's a policy
    vocabulary shared across regulatory-intelligence entities, not a
    per-entity lifecycle, so it lives here instead of on one module.
    """

    FAIL_CLOSED = "FAIL_CLOSED"
    REQUEST_INPUT = "REQUEST_INPUT"
    HUMAN_REVIEW = "HUMAN_REVIEW"
