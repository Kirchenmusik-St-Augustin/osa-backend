"""Route-wide authentication checks. The routes are enumerated from the
application's OpenAPI document, so a route is covered the moment it exists,
whichever router file it lives in: a route that forgets its guard fails here,
and a new public or member-reachable route needs a deliberate edit of the
lists below."""

import uuid

import pytest

from main import app

Route = tuple[str, str]

# Routes that are public by design (open, or authenticated by something other
# than the bearer token: the refresh cookie, a token in the body, a Google
# credential). Adding a route here is a security decision and has to be
# reviewed as one.
PUBLIC_ROUTES: frozenset[Route] = frozenset(
    {
        ("GET", "/"),
        ("GET", "/go/"),
        ("GET", "/go/{path}"),
        ("POST", "/auth/forgot-password"),
        ("POST", "/auth/google/callback"),
        ("POST", "/auth/google/link"),
        ("POST", "/auth/login"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/register"),
        ("POST", "/auth/reset-password"),
        ("POST", "/auth/verify-email"),
    }
)

# Routes a verified member WITHOUT any role may use. Everything else answers
# 403, also for requests whose body would not validate.
MEMBER_ROUTES: frozenset[Route] = frozenset(
    {
        ("DELETE", "/auth/oauth2/{binding_id}"),
        ("GET", "/auth/me"),
        ("GET", "/performances"),
        ("GET", "/performances/{performance_id}"),
        ("GET", "/performances/{performance_id}/my-booking-status"),
        ("GET", "/profile"),
        ("GET", "/statistics"),
        ("GET", "/support/contactpersons"),
        ("GET", "/support/requests-and-bookings"),
        ("GET", "/system/environment"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/resend-verification-email"),
        ("POST", "/performances/{performance_id}/booking-status"),
        ("POST", "/support/message-to-contactperson"),
        ("PUT", "/profile"),
    }
)

# Routes that still check the request body before the permission, so a member
# gets a validation error (422) instead of the 403. The set may only shrink.
VALIDATED_BEFORE_AUTHORIZATION: frozenset[Route] = frozenset(
    {
        ("POST", "/coreelements/{element_type}"),
        ("PUT", "/coreelements/{element_type}/{element_id}"),
    }
)

_PATH_PARAMETER_VALUES = {
    "{element_type}": "instrument",
    "{direction}": "up",
    "{path}": "x",
}


def _concrete_path(path: str) -> str:
    return "/".join(
        _PATH_PARAMETER_VALUES.get(
            segment, str(uuid.uuid4()) if segment.startswith("{") else segment
        )
        for segment in path.split("/")
    )


def _routes() -> list[Route]:
    """Every (method, path) of the application, taken from its OpenAPI
    document (FastAPI keeps included routers lazy, so `app.routes` does not
    list them)."""
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    )


@pytest.mark.parametrize(
    ("method", "path"), [route for route in _routes() if route not in PUBLIC_ROUTES]
)
def test_a_route_without_credentials_is_rejected_unless_it_is_public(
    client, method: str, path: str
):
    response = client.request(method, _concrete_path(path), json={})

    assert response.status_code == 401, (
        f"{method} {path} answered {response.status_code}"
    )


def test_every_listed_route_still_exists():
    existing = set(_routes())

    assert existing >= PUBLIC_ROUTES
    assert existing >= MEMBER_ROUTES
    assert existing >= VALIDATED_BEFORE_AUTHORIZATION


def test_a_member_without_roles_reaches_exactly_the_member_routes(client, make_user):
    member = make_user(password="correct-password", roles=[])
    token = client.post(
        "/auth/login", data={"username": member.email, "password": "correct-password"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # The logout ends the very session used here, so it is requested last.
    probed = [route for route in _routes() if route not in PUBLIC_ROUTES]
    probed.sort(key=lambda route: route == ("POST", "/auth/logout"))
    reachable = {
        (method, path)
        for method, path in probed
        if client.request(
            method, _concrete_path(path), json={}, headers=headers
        ).status_code
        != 403
    }

    assert reachable == MEMBER_ROUTES | VALIDATED_BEFORE_AUTHORIZATION
