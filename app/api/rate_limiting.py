"""Rate limits that count per account instead of per client address.

Lives in the API layer because the key reads the bearer token
(app.api.deps); the address-based limiter itself is app.core.rate_limit.
"""

from typing import TYPE_CHECKING, cast

# Needed at runtime: slowapi resolves the annotations of the key function.
from starlette.requests import Request

from app.api.deps import try_decode_token
from app.core.rate_limit import client_ip, limiter

if TYPE_CHECKING:
    from collections.abc import Callable

# Every mail sent on behalf of a user counts against the global mail kill
# switch, so all endpoints that queue such a mail share one quota per account.
# The explicit scope matters: slowapi counts per request path by default, which
# would give every performance id in a path its own counter.
MAIL_ACTION_LIMIT = "10/hour"
MAIL_ACTION_SCOPE = "mail-action"


def user_or_client_key(request: Request) -> str:
    """Key for limits on authenticated actions: the account named by the
    bearer token, so one user cannot multiply a quota by changing address;
    anonymous or invalid callers fall back to their client address."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        email = try_decode_token(header[len("bearer ") :])
        if email is not None:
            return f"user:{email}"
    return client_ip(request)


def rate_limited_per_user[**P, R](
    limit: str, scope: str
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Like rate_limited(), but counted per account instead of per address,
    and per `scope` instead of per request path. The same rule applies: a
    decorated endpoint must declare a literal "request: Request" parameter."""
    return cast(
        "Callable[[Callable[P, R]], Callable[P, R]]",
        limiter.shared_limit(limit, scope=scope, key_func=user_or_client_key),
    )
