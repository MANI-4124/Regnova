from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db_session
from app.modules.auth.dependencies import get_current_active_user
from app.modules.internal_role_assignment.models import InternalRoleCode
from app.modules.internal_role_assignment.repository import InternalRoleAssignmentRepository
from app.modules.user.models import User

from .exceptions import PermissionDenied
from .service import RBACService


def require_admin(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:

    RBACService.require_role(
        db,
        current_user,
        "ADMIN",
    )

    return current_user


def require_manager(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:

    RBACService.require_role(
        db,
        current_user,
        "ADMIN",
        "MANAGER",
    )

    return current_user


def require_employee(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:

    RBACService.require_role(
        db,
        current_user,
        "ADMIN",
        "MANAGER",
        "EMPLOYEE",
    )

    return current_user


def require_ceo(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    The single permanent-admin ("CEO") seat - see User.is_permanent_admin.
    A different check from require_admin: this is one specific account,
    not a role tier any ADMIN-tenured user could hold.
    """

    if not current_user.is_permanent_admin:
        raise PermissionDenied()

    return current_user


def _has_active_role(db: Session, user_id, role_code: str) -> bool:
    return InternalRoleAssignmentRepository(db).get_active_for_user_role(
        user_id,
        role_code,
    ) is not None


def _require_internal_role(
    current_user: User,
    db: Session,
    role_code: str,
) -> User:
    assignment = InternalRoleAssignmentRepository(db).get_active_for_user_role(
        current_user.id,
        role_code,
    )

    if assignment is None:
        raise PermissionDenied()

    return current_user


def require_ra(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:
    return _require_internal_role(current_user, db, InternalRoleCode.RA.value)


def require_senior_reviewer(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:
    return _require_internal_role(current_user, db, InternalRoleCode.SENIOR_REVIEWER.value)


def require_submission_operations(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:
    return _require_internal_role(current_user, db, InternalRoleCode.SUBMISSION_OPERATIONS.value)


def require_platform_admin(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:
    return _require_internal_role(current_user, db, InternalRoleCode.PLATFORM_ADMIN.value)


def require_regulatory_content_writer(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:
    """
    REGULATORY_KNOWLEDGE_LEAD only - deliberately not RA/Senior Reviewer
    too, even though FR-13 lists "authorized RA reviewer" as a Graph
    Console actor: B2's own permission table gives RA/Senior Reviewer
    authority over assessment-side data (findings, review decisions),
    not regulatory-content authoring, which FR-13 frames as the
    Knowledge Lead's specific responsibility. See CLAUDE.md "Internal
    role model".

    Gates RegulatoryBasisRelease writes (assembling an already-verified
    release stays Knowledge-Lead-only, not delegable to an advisor), and
    the verify()/activate()/reject() transitions on Source/Requirement/
    Rule versions - see require_regulatory_content_author below for
    drafting those, and CLAUDE.md "Regulatory content approval workflow"
    for the full split.
    """

    return _require_internal_role(current_user, db, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value)


def require_regulatory_content_author(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db_session),
) -> User:
    """
    Drafting/editing-while-DRAFT/submitting-for-review on Source/
    Requirement/Rule versions: REGULATORY_CONTENT_ADVISOR or
    REGULATORY_KNOWLEDGE_LEAD (Knowledge Lead is a strict superset, same
    shape as require_manager including ADMIN). Does NOT grant verify/
    activate/reject authority - see require_regulatory_content_writer
    above and CLAUDE.md "Regulatory content approval workflow". This
    router-level check is a floor; ContentReviewWorkflow re-checks the
    precise authority each transition needs in the service layer, the
    same defense-in-depth precedent finding/service.py already
    establishes.
    """

    if _has_active_role(db, current_user.id, InternalRoleCode.REGULATORY_CONTENT_ADVISOR.value):
        return current_user

    return _require_internal_role(current_user, db, InternalRoleCode.REGULATORY_KNOWLEDGE_LEAD.value)