"""
Requirement Result module - no public router, same shape as audit's
OutboxEvent (system-produced lineage data, not user-facing CRUD).
"""

from .models import RequirementResult

__all__ = (
    "RequirementResult",
)
