from __future__ import annotations

from app.modules.auth.jwt import create_access_token
from app.modules.auth.security import hash_password
from app.modules.user.models import User


def test_require_role_rejects_role_from_another_organization(client, db, tenant_a, tenant_b):
    """
    RBACService.require_role used to fetch the role by id alone
    (db.get(Role, user.role_id)), with no check that the role actually
    belongs to the user's organization_id. Plant a user in org A whose
    role_id points at org B's ADMIN role, and confirm the lookup is now
    scoped to the caller's own org - and rejects it - instead of trusting
    whatever organization owns that role id.
    """

    rogue_user = User(
        organization_id=tenant_a["organization"].id,
        role_id=tenant_b["role"].id,
        first_name="Rogue",
        last_name="User",
        email="rogue@example.com",
        password_hash=hash_password("Password123!"),
    )
    db.add(rogue_user)
    db.commit()

    token = create_access_token(
        subject=str(rogue_user.id),
        additional_claims={
            "organization_id": str(tenant_a["organization"].id),
            "role_id": str(tenant_b["role"].id),
        },
    )

    response = client.post(
        "/roles",
        json={"code": "SNEAKY", "name": "Sneaky"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
