from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.shorturl import Shorturl
from app.schemas.shorturl import ShorturlListResponse, ShorturlRequest, ShorturlResponse


class ShorturlNotFoundError(Exception):
    """Raised when `shorturl_id` doesn't exist."""


class ShorturlValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 fee_service.FeeValidationError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Shorturl validation failed")


def ensure_scheme(url: str) -> str:
    """Prepends "http://" if `url` has no scheme of its own. 1:1 Legacy's
    `ShorturlController::ensureScheme()` -- Legacy duplicates this exact
    logic a second time inline in `GoController::go()` at redirect time;
    here it is one shared function, called from both the save path
    (create_shorturl/update_shorturl) and the redirect path
    (resolve_and_record_hit) below, same net behavior without the
    duplication."""
    if not urlparse(url).scheme:
        return f"http://{url}"
    return url


def _path_taken(db: Session, path: str, exclude_id: int | None) -> bool:
    stmt = select(Shorturl.id).where(Shorturl.path == path)
    if exclude_id is not None:
        stmt = stmt.where(Shorturl.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _validate(db: Session, path: str, exclude_id: int | None) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    if _path_taken(db, path, exclude_id):
        errors.append(("path", "Der Pfad ist bereits vergeben."))
    return errors


def _get_or_404(db: Session, shorturl_id: int) -> Shorturl:
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
    # 1:1 Legacy's `Shorturl::all()->sortBy('path')`.
    shorturls = db.execute(select(Shorturl).order_by(Shorturl.path)).scalars().all()
    return [_to_response(shorturl) for shorturl in shorturls]


def list_shorturls_with_prefix(db: Session) -> ShorturlListResponse:
    # `urlprefix` mirrors Legacy's hardcoded `'urlprefix' =>
    # 'https://go.hochamt.at/'` in ShorturlController::index() -- built
    # from Settings.shorturl_domain instead so dev (go.hochamt.at.dev.
    # schimpl.cc) vs. prod (go.hochamt.at) is a config difference, not a
    # code difference.
    return ShorturlListResponse(
        urlprefix=f"https://{get_settings().shorturl_domain}/",
        items=list_shorturls(db),
    )


def create_shorturl(db: Session, data: ShorturlRequest) -> ShorturlResponse:
    # `lstrip` only -- 1:1 Legacy's `ltrim($validated['path'], '/')`,
    # strips leading slashes only, not trailing/embedded ones.
    path = data.path.lstrip("/")
    errors = _validate(db, path, exclude_id=None)
    if errors:
        raise ShorturlValidationError(errors)

    now = datetime.now(UTC)
    shorturl = Shorturl(
        path=path,
        target=ensure_scheme(data.target),
        counter=0,
        created_at=now,
        updated_at=now,
    )
    db.add(shorturl)
    db.commit()
    return _to_response(shorturl)


def update_shorturl(
    db: Session, shorturl_id: int, data: ShorturlRequest
) -> ShorturlResponse:
    shorturl = _get_or_404(db, shorturl_id)
    path = data.path.lstrip("/")
    errors = _validate(db, path, exclude_id=shorturl_id)
    if errors:
        raise ShorturlValidationError(errors)

    shorturl.path = path
    shorturl.target = ensure_scheme(data.target)
    shorturl.updated_at = datetime.now(UTC)
    db.commit()
    return _to_response(shorturl)


def delete_shorturl(db: Session, shorturl_id: int) -> None:
    # No has_dependencies check -- Legacy's own DestroyRequest has an empty
    # rules() too, no other table references shorturls.id.
    shorturl = _get_or_404(db, shorturl_id)
    db.delete(shorturl)
    db.commit()


def resolve_and_record_hit(db: Session, path: str) -> str | None:
    """Looks up `path` for the public go-redirect endpoint. On a hit,
    records the click (counter/latestcall_at, 1:1 GoController::go()) and
    returns the normalized target URL; returns None on a miss (the router
    turns that into a 404). No special-casing for any particular path
    value (e.g. Legacy's "listAll") -- see app.api.router_includes.go for
    why that public dump was deliberately not ported."""
    result = db.execute(select(Shorturl).where(Shorturl.path == path))
    shorturl = result.scalar_one_or_none()
    if shorturl is None:
        return None

    shorturl.counter += 1
    shorturl.latestcall_at = datetime.now(UTC)
    db.commit()
    return ensure_scheme(shorturl.target)
