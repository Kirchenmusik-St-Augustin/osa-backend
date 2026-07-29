from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.db.models.user import User
from app.services.permission_service import calculate_permissions


def ensure_permission(user: User, required_permission: str) -> None:
    """Raises 403 if `user` lacks `required_permission`. Used directly
    (not via `require_permission` below) by routers whose required
    permission depends on request data only known at call time -- e.g. the
    Coreelement router's `element_type` path param selects one of six
    different permissions, which `require_permission`'s route-declaration-
    time factory can't express."""
    if required_permission not in calculate_permissions(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Fehlende Berechtigung: {required_permission}",
        )


def require_permission(required_permission: str) -> Callable[..., User]:
    """Usage: Depends(require_permission("userMaintain"))"""

    def _guard(current_user: User = Depends(get_current_user)) -> User:
        ensure_permission(current_user, required_permission)
        return current_user

    return _guard
