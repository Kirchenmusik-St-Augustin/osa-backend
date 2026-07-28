from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.db.models.user import User
from app.services.permission_service import calculate_permissions


def require_permission(required_permission: str) -> Callable[..., User]:
    """Usage: Depends(require_permission("userMaintain"))"""

    def _guard(current_user: User = Depends(get_current_user)) -> User:
        if required_permission not in calculate_permissions(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Fehlende Berechtigung: {required_permission}",
            )
        return current_user

    return _guard
