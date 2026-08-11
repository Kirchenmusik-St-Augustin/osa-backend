import pytest
from fastapi import HTTPException

from app.api.auth_guards import get_verified_user, require_permission


def test_get_verified_user_allows_a_verified_user(make_user):
    user = make_user()  # verified=True by default

    assert get_verified_user(current_user=user) is user


def test_get_verified_user_rejects_an_unverified_user(make_user):
    user = make_user(verified=False)

    with pytest.raises(HTTPException) as exc_info:
        get_verified_user(current_user=user)

    assert exc_info.value.status_code == 403


def test_require_permission_allows_user_with_permission(make_user):
    admin = make_user(administrator=True)
    guard = require_permission("userMaintain")

    result = guard(current_user=admin)

    assert result is admin


def test_require_permission_rejects_user_without_permission(make_user):
    plain_user = make_user(administrator=False)
    guard = require_permission("userMaintain")

    with pytest.raises(HTTPException) as exc_info:
        guard(current_user=plain_user)

    assert exc_info.value.status_code == 403
    assert "userMaintain" in exc_info.value.detail
