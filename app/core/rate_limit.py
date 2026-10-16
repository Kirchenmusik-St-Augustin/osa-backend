from typing import TYPE_CHECKING, cast

from slowapi import Limiter

# Needed at runtime: slowapi resolves the annotations of the key function.
from starlette.requests import Request  # noqa: TC002

if TYPE_CHECKING:
    from collections.abc import Callable


def client_ip(request: Request) -> str:
    """The caller's address as uvicorn resolved it: the X-Forwarded-For value
    set by the trusted Caddy hop (gunicorn --forwarded-allow-ips, see the
    Dockerfile), never the address of the local proxy connection."""
    return request.client.host if request.client else "unknown"


# Per-IP rate limiting for endpoints that only need a plain request limiter
# (e.g. /refresh).
#
# The login endpoint's own 5-attempts/60s lockout is NOT built on this
# limiter -- it needs asymmetric "hit on failure, clear on success"
# semantics, which a blanket per-endpoint request limiter cannot express.
# See app.services.auth_service.check_login_throttle instead.
limiter = Limiter(key_func=client_ip)


def rate_limited[**P, R](limit: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Typed wrapper around Limiter.limit(): slowapi ships no type
    information, so the decorator is cast once here instead of suppressing the
    type checker at every use site. A decorated endpoint must declare a
    literal "request: Request" parameter even if its body never reads it:
    slowapi looks the request up by that name."""
    return cast("Callable[[Callable[P, R]], Callable[P, R]]", limiter.limit(limit))
