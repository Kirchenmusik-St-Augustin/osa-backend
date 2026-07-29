from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.artist import Artist
from app.db.models.performance_proprium import PerformanceProprium
from app.db.models.propriumwork import Propriumwork
from app.schemas.propriumwork import (
    PropriumworkRequest,
    PropriumworkResponse,
    PropriumworkSearchResult,
)
from app.services.artist_service import label_for

_NAME_MIN_LENGTH = 3
_NAME_MAX_LENGTH = 60
# Legacy quirk, confirmed 1:1: Propriumwork requires min:1 here, while
# Ordinariumwork (ordinariumwork_service.py) allows min:0 -- not a typo,
# the two SaveRequest classes genuinely differ on this bound.
_DURATION_MIN = 1
_DURATION_MAX = 999
_SEARCH_RESULT_LIMIT = 20
_NAME_LENGTH_ERROR = (
    f"Muss zwischen {_NAME_MIN_LENGTH} und {_NAME_MAX_LENGTH} Zeichen lang sein."
)


class PropriumworkNotFoundError(Exception):
    """Raised when `propriumwork_id` doesn't exist."""


class PropriumworkValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 auth_service.RegistrationConflictError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Propriumwork validation failed")


class PropriumworkInUseError(Exception):
    """Raised when delete is blocked by a Performance referencing this
    Propriumwork -- Legacy's only HasDependencies target (`performances`),
    retrofitted now that Schritt 5 built that domain. Unlike Ordinariumwork
    (a direct `ordinariumwork_id` column on `performances`), a Propriumwork
    is only referenced through the `performance_proprium` pivot table."""


def _get_or_404(db: Session, propriumwork_id: int) -> Propriumwork:
    result = db.execute(select(Propriumwork).where(Propriumwork.id == propriumwork_id))
    propriumwork = result.scalar_one_or_none()
    if propriumwork is None:
        raise PropriumworkNotFoundError
    return propriumwork


def _validate(
    db: Session, data: PropriumworkRequest, exclude_id: int | None
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []

    if not _NAME_MIN_LENGTH <= len(data.name) <= _NAME_MAX_LENGTH:
        errors.append(("name", _NAME_LENGTH_ERROR))

    if (
        db.execute(
            select(Artist.id).where(Artist.id == data.artist_id)
        ).scalar_one_or_none()
        is None
    ):
        errors.append(("artist_id", "Komponist/in wurde nicht gefunden."))

    if (
        data.duration is not None
        and not _DURATION_MIN <= data.duration <= _DURATION_MAX
    ):
        errors.append(
            ("duration", f"Muss zwischen {_DURATION_MIN} und {_DURATION_MAX} liegen.")
        )

    stmt = select(Propriumwork.id).where(
        func.lower(Propriumwork.name) == data.name.lower(),
        Propriumwork.artist_id == data.artist_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(Propriumwork.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        errors.append(
            ("name", "Dieses Werk ist für diesen Komponisten bereits erfasst.")
        )

    return errors


def _to_response(db: Session, propriumwork: Propriumwork) -> PropriumworkResponse:
    artist = db.execute(
        select(Artist).where(Artist.id == propriumwork.artist_id)
    ).scalar_one_or_none()
    return PropriumworkResponse(
        id=propriumwork.id,
        name=propriumwork.name,
        description=propriumwork.description,
        artist_id=propriumwork.artist_id,
        artist_name=label_for(artist) if artist else "",
        duration=propriumwork.duration,
        demanding=propriumwork.demanding,
    )


def search_propriumworks(db: Session, query: str) -> Sequence[PropriumworkSearchResult]:
    """Real indexed-ish DB query, replacing Legacy's
    `Propriumwork::search()` anti-pattern (loads the entire table into
    PHP, filters in memory, then a dead `sortBy('artist_name')` call that
    never actually sorted -- an obvious oversight, corrected here with a
    real ORDER BY instead of replicated verbatim)."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return []

    combined = func.lower(
        Artist.surname + " " + Artist.givenname + " " + Propriumwork.name
    )
    stmt = (
        select(Propriumwork, Artist)
        .join(Artist, Propriumwork.artist_id == Artist.id)
        .where(*[combined.like(f"%{word}%") for word in words])
        .order_by(Artist.surname, Artist.givenname, Propriumwork.name)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    rows = db.execute(stmt).all()
    return [
        PropriumworkSearchResult(
            id=propriumwork.id, label=f"{label_for(artist)}: {propriumwork.name}"
        )
        for propriumwork, artist in rows
    ]


def create_propriumwork(db: Session, data: PropriumworkRequest) -> PropriumworkResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise PropriumworkValidationError(errors)

    now = datetime.now(UTC)
    propriumwork = Propriumwork(
        name=data.name,
        description=data.description,
        artist_id=data.artist_id,
        duration=data.duration,
        demanding=data.demanding,
        created_at=now,
        updated_at=now,
    )
    db.add(propriumwork)
    db.commit()
    return _to_response(db, propriumwork)


def update_propriumwork(
    db: Session, propriumwork_id: int, data: PropriumworkRequest
) -> PropriumworkResponse:
    propriumwork = _get_or_404(db, propriumwork_id)
    errors = _validate(db, data, exclude_id=propriumwork_id)
    if errors:
        raise PropriumworkValidationError(errors)

    propriumwork.name = data.name
    propriumwork.description = data.description
    propriumwork.artist_id = data.artist_id
    propriumwork.duration = data.duration
    propriumwork.demanding = data.demanding
    propriumwork.updated_at = datetime.now(UTC)
    db.commit()
    return _to_response(db, propriumwork)


def get_propriumwork(db: Session, propriumwork_id: int) -> PropriumworkResponse:
    propriumwork = _get_or_404(db, propriumwork_id)
    return _to_response(db, propriumwork)


def _propriumwork_has_dependencies(db: Session, propriumwork_id: int) -> bool:
    count = db.execute(
        select(func.count())
        .select_from(PerformanceProprium)
        .where(PerformanceProprium.propriumwork_id == propriumwork_id)
    ).scalar_one()
    return count > 0


def delete_propriumwork(db: Session, propriumwork_id: int) -> None:
    propriumwork = _get_or_404(db, propriumwork_id)
    if _propriumwork_has_dependencies(db, propriumwork_id):
        raise PropriumworkInUseError
    db.delete(propriumwork)
    db.commit()
