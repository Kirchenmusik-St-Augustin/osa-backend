"""The login flow of the API tests in one place: real sign-in through
`/auth/login`, answered with the Authorization header of the new session."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient

    from app.db.models.user import User

DEFAULT_PASSWORD = "correct-password"


def login_with_credentials(
    client: TestClient, email: str, password: str
) -> dict[str, str]:
    """Signs in with an e-mail address and a password and returns the
    Authorization header of the new session."""
    response = client.post(
        "/auth/login", data={"username": email, "password": password}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def login_as(
    client: TestClient, user: User, password: str = DEFAULT_PASSWORD
) -> dict[str, str]:
    """Signs in an existing user and returns the Authorization header."""
    return login_with_credentials(client, user.email, password)


def login_headers(
    client: TestClient, make_user: Callable[..., User], **user_kwargs: object
) -> dict[str, str]:
    """Creates a user (the keyword arguments of `make_user`, for example
    `roles` or `administrator`) and signs them in."""
    user = make_user(password=DEFAULT_PASSWORD, **user_kwargs)
    return login_as(client, user)
