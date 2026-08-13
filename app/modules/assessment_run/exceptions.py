from __future__ import annotations

from app.common.exceptions import ConflictException, NotFoundException, ValidationException


class AssessmentRunNotFound(NotFoundException):
    error_code = "ASSESSMENT_RUN_NOT_FOUND"

    def __init__(self):
        super().__init__("Assessment run not found")


class UnsupportedDimension(ValidationException):
    error_code = "UNSUPPORTED_DIMENSION"

    def __init__(self, dimension: str, supported: frozenset[str]):
        super().__init__(
            f"Dimension {dimension!r} is not supported yet "
            f"(supported: {sorted(supported)})",
        )


class AssessmentRunMissingRegulatoryBasis(ConflictException):
    error_code = "ASSESSMENT_RUN_MISSING_REGULATORY_BASIS"

    def __init__(self):
        super().__init__(
            "This Product x Market state has no active Regulatory Basis "
            "Release pinned yet - cannot run an assessment against it",
        )
