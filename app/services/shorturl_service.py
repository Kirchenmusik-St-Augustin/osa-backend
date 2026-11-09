from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import select, update

from app.core.config import get_settings
from app.db.models.shorturl import Shorturl
from app.schemas.shorturl import ShorturlListResponse, ShorturlRequest, ShorturlResponse
from app.services.errors import DomainValidationError, FieldError, NotFoundError

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


_TARGET_SCHEME_MESSAGE = "Nur http- und https-Adressen sind erlaubt."


class ShorturlNotFoundError(NotFoundError):
    """Raised when `shorturl_id` doesn't exist."""


class ShorturlValidationError(DomainValidationError):
    """Field-level validation failures, one (field, message) pair per
    failing field -- same pattern as fee_service.FeeValidationError."""


def normalize_target(url: str) -> str:
    """Redirect targets are http(s) addresses only: a missing scheme becomes
    https, anything else (javascript:, data:, file:, ftp:, a bare //host) or
    an address without a usable host is refused. One shared function, called
    from both the save path (create_shorturl/update_shorturl) and the
    redirect path (resolve_and_record_hit) below."""
    candidate = url.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    try:
        # A non-numeric "port" is how a scheme-less javascript:/data: input
        # presents itself after the default scheme was added.
        parsed.port  # noqa: B018 -- raises ValueError for an invalid port
    except ValueError:
        raise ValueError(_TARGET_SCHEME_MESSAGE) from None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError(_TARGET_SCHEME_MESSAGE)
    return candidate


def _path_taken(db: Session, path: str, exclude_id: uuid.UUID | None) -> bool:
    stmt = select(Shorturl.id).where(Shorturl.path == path)
    if exclude_id is not None:
        stmt = stmt.where(Shorturl.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _validate(db: Session, path: str, exclude_id: uuid.UUID | None) -> list[FieldError]:
    errors: list[FieldError] = []
    if _path_taken(db, path, exclude_id):
        errors.append(FieldError("path", "Der Pfad ist bereits vergeben."))
    return errors


def _get_or_404(db: Session, shorturl_id: uuid.UUID) -> Shorturl:
    result = db.execute(select(Shorturl).where(Shorturl.id == shorturl_id))
    shorturl = result.scalar_one_or_none()
    if shorturl is None:
        raise ShorturlNotFoundError
    return shorturl


def _to_response(shorturl: Shorturl) -> ShorturlResponse:
    return ShorturlResponse(
        id=shorturl.id,
        path=shorturl.path,
        target=shorturl.target,
        counter=shorturl.counter,
        latestcall_at=shorturl.latestcall_at,
    )


def list_shorturls(db: Session) -> list[ShorturlResponse]:
    # Alphabetical by path.
    shorturls = db.execute(select(Shorturl).order_by(Shorturl.path)).scalars().all()
    return [_to_response(shorturl) for shorturl in shorturls]


def list_shorturls_with_prefix(db: Session) -> ShorturlListResponse:
    # `urlprefix` is built from Settings.shorturl_domain so dev
    # (go.hochamt.at.dev.schimpl.cc) vs. prod (go.hochamt.at) is a config
    # difference, not a code difference.
    return ShorturlListResponse(
        urlprefix=f"https://{get_settings().shorturl_domain}/",
        items=list_shorturls(db),
    )


def _validated_path_and_target(
    db: Session, data: ShorturlRequest, exclude_id: uuid.UUID | None
) -> tuple[str, str]:
    errors = _validate(db, data.path, exclude_id)
    target = ""
    try:
        target = normalize_target(data.target)
    except ValueError as exc:
        errors.append(FieldError("target", str(exc)))
    if errors:
        raise ShorturlValidationError(errors)
    return data.path, target


def create_shorturl(db: Session, data: ShorturlRequest) -> ShorturlResponse:
    path, target = _validated_path_and_target(db, data, exclude_id=None)
    shorturl = Shorturl(path=path, target=target, counter=0)
    db.add(shorturl)
    db.commit()
    return _to_response(shorturl)


def update_shorturl(
    db: Session, shorturl_id: uuid.UUID, data: ShorturlRequest
) -> ShorturlResponse:
    shorturl = _get_or_404(db, shorturl_id)
    path, target = _validated_path_and_target(db, data, exclude_id=shorturl_id)
    shorturl.path = path
    shorturl.target = target
    db.commit()
    return _to_response(shorturl)


def delete_shorturl(db: Session, shorturl_id: uuid.UUID) -> None:
    # No has_dependencies check -- no other table references shorturls.id.
    shorturl = _get_or_404(db, shorturl_id)
    db.delete(shorturl)
    db.commit()


def resolve_and_record_hit(db: Session, path: str) -> str | None:
    """Looks up `path` for the public go-redirect endpoint. On a hit,
    records the click and returns the target URL; returns None on a miss or
    when the stored target is not a valid http(s) address (the router turns
    that into a 404). The click is counted by one atomic UPDATE ...
    RETURNING, so concurrent clicks are all counted and the lookup costs one
    statement. No special-casing for any particular path value (e.g.
    "listAll") -- see app.api.router_includes.go for why there is no public
    dump path."""
    stored_target = db.execute(
        update(Shorturl)
        .where(Shorturl.path == path)
        .values(counter=Shorturl.counter + 1, latestcall_at=datetime.now(UTC))
        .returning(Shorturl.target)
    ).scalar_one_or_none()
    db.commit()
    if stored_target is None:
        return None
    try:
        return normalize_target(stored_target)
    except ValueError:
        return None
