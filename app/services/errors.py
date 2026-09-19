"""Shared exception base classes for the service layer's error reporting.

Every domain service raises one of these (or a same-shaped domain
subclass, e.g. `ArtistNotFoundError(NotFoundError)`) instead of returning
error codes or duplicating HTTP-response construction. app.api.
exception_handlers maps each base to its HTTP response in exactly one
place, so routers never need a try/except for these cases.

Named `DomainValidationError`, not `ValidationError`, to stay distinct
from `pydantic.ValidationError` -- main.py already registers a handler
for that one, and importing both unaliased into the same module would
collide.
"""

from typing import NamedTuple


class NotFoundError(Exception):
    """The requested row doesn't exist. Renders as a generic 404."""


class FieldError(NamedTuple):
    """One field-level validation failure. A NamedTuple, not a plain
    dataclass, so it still compares equal to a bare `(field, message)`
    tuple -- existing tests written against that shape keep working."""

    field: str
    message: str


class DomainValidationError(Exception):
    """Field-level validation failures, one FieldError per failing field
    -- rendered as FastAPI's own {"detail": [...]} validation-error
    shape, identical to what Pydantic's built-in 422s produce."""

    def __init__(self, errors: list[FieldError]) -> None:
        self.errors = errors
        super().__init__(type(self).__name__)


class GeneralValidationError(DomainValidationError):
    """A single validation failure with no one input field to blame -- a
    delete blocked by a dependent row, an administrator-protected
    account, a wrong current password, etc. Same wire shape as
    DomainValidationError with exactly one FieldError; `field` defaults
    to "general", the catch-all name the frontend falls back to when no
    specific input owns the error."""

    def __init__(self, message: str, *, field: str = "general") -> None:
        super().__init__([FieldError(field, message)])


class PlainError(Exception):
    """A domain error that renders as FastAPI's own bare
    `{"detail": "<message>"}` shape instead of DomainValidationError's
    field-level array -- for the handful of cases that already used a
    plain string detail before this hierarchy existed and whose frontend
    surface expects that shape. Each subclass fixes its own
    `status_code`; only the message varies per raise site."""

    status_code: int

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class ForbiddenError(PlainError):
    """A domain rule blocks the action outright, not a field validation
    failure -- e.g. editing a performance whose schedule has already
    passed. Renders as a plain 403."""

    status_code = 403
