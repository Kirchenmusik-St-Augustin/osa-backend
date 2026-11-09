"""Endpoints that queue a mail on behalf of a user are limited per account:
every such mail counts against the global mail kill switch, so one
self-registered account must not be able to exhaust it."""

import uuid

import pytest
from starlette.requests import Request

from app.api.rate_limiting import MAIL_ACTION_LIMIT, user_or_client_key
from tests.login import login_as

_PASSWORD = "correct-password"
_ALLOWED_PER_WINDOW = int(MAIL_ACTION_LIMIT.split("/")[0])


def _contactperson_message(client, user, headers: dict[str, str]):
    del user
    return client.post(
        "/support/message-to-contactperson",
        json={"recipient_id": str(uuid.uuid4()), "message": "Hallo Welt"},
        headers=headers,
    )


def _cast_message(client, user, headers: dict[str, str]):
    del user
    return client.post(
        f"/performances/{uuid.uuid4()}/message-to-cast/send",
        json={"recipient_ids": [str(uuid.uuid4())], "message": "Hallo!"},
        headers=headers,
    )


def _profile_update(client, user, headers: dict[str, str]):
    return client.put(
        "/profile",
        json={
            "givenname": "Max",
            "surname": "Muster",
            "email": user.email,
            "phone": "+43 660 1234567",
            "change_password": False,
            "password": None,
            "password_confirmation": None,
            "auth_password": _PASSWORD,
        },
        headers=headers,
    )


_ENDPOINTS = [
    pytest.param(_contactperson_message, ["planner"], id="message-to-contactperson"),
    pytest.param(_cast_message, ["disponent"], id="message-to-cast"),
    pytest.param(_profile_update, [], id="profile-update"),
]


def _account(make_user, roles: list[str]):
    return make_user(
        email=f"{uuid.uuid4().hex[:12]}@example.com", password=_PASSWORD, roles=roles
    )


@pytest.mark.parametrize(("send", "roles"), _ENDPOINTS)
def test_the_quota_is_counted_per_account(client, make_user, send, roles):
    sender = _account(make_user, roles)
    other_sender = _account(make_user, roles)
    sender_headers = login_as(client, sender, _PASSWORD)

    statuses = [
        send(client, sender, sender_headers).status_code
        for _ in range(_ALLOWED_PER_WINDOW + 1)
    ]
    other_status = send(
        client, other_sender, login_as(client, other_sender, _PASSWORD)
    ).status_code

    assert 429 not in statuses[:_ALLOWED_PER_WINDOW]
    assert statuses[_ALLOWED_PER_WINDOW] == 429
    assert other_status != 429


def test_all_mail_actions_of_an_account_share_one_quota(client, make_user):
    sender = _account(make_user, ["disponent"])
    headers = login_as(client, sender, _PASSWORD)
    half = _ALLOWED_PER_WINDOW // 2

    for _ in range(half):
        _contactperson_message(client, sender, headers)
    for _ in range(_ALLOWED_PER_WINDOW - half):
        _profile_update(client, sender, headers)

    assert _cast_message(client, sender, headers).status_code == 429


def test_the_limit_follows_the_account_across_addresses(client, make_user):
    sender = _account(make_user, [])
    headers = login_as(client, sender, _PASSWORD)
    for _ in range(_ALLOWED_PER_WINDOW):
        _contactperson_message(client, sender, headers)

    response = client.post(
        "/support/message-to-contactperson",
        json={"recipient_id": str(uuid.uuid4()), "message": "Hallo Welt"},
        headers={**headers, "X-Forwarded-For": "203.0.113.77"},
    )

    assert response.status_code == 429


def _request_with(authorization: str | None) -> Request:
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request(
        {"type": "http", "headers": headers, "client": ("203.0.113.9", 4711)}
    )


def test_key_is_the_account_named_by_a_valid_bearer_token(client, make_user):
    user = make_user(password=_PASSWORD)
    token = login_as(client, user, _PASSWORD)["Authorization"]

    assert user_or_client_key(_request_with(token)) == f"user:{user.email}"


@pytest.mark.parametrize(
    "authorization", [None, "Bearer not-a-jwt", "Basic dXNlcjpwYXNz"]
)
def test_key_falls_back_to_the_client_address(authorization):
    assert user_or_client_key(_request_with(authorization)) == "203.0.113.9"
