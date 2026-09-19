from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.human_names import label_for_name, normalize_givenname, normalize_surname
from app.db.models.artist import Artist
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.propriumwork import Propriumwork
from app.services.errors import (
    DomainValidationError,
    FieldError,
    GeneralValidationError,
    NotFoundError,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from app.schemas.artist import ArtistRequest

_NAME_MIN_LENGTH = 3
_NAME_MAX_LENGTH = 32
_SEARCH_RESULT_LIMIT = 20
_IN_USE_DETAIL = "Das Element kann nicht gelöscht werden, da es noch in Verwendung ist."


class ArtistNotFoundError(NotFoundError):
    """Raised when `artist_id` doesn't exist."""


class ArtistValidationError(DomainValidationError):
    """Field-level validation failures, one (field, message) pair per
    failing field -- same pattern as auth_service.RegistrationConflictError."""


class ArtistInUseError(GeneralValidationError):
    """Raised when delete is blocked by a dependent Ordinariumwork/
    Propriumwork/Performance row."""

    def __init__(self) -> None:
        super().__init__(_IN_USE_DETAIL)


def label_for(artist: Artist) -> str:
    """Display label ("SURNAME, Givenname"), used in search results and
    embedded in Ordinariumwork/Propriumwork responses."""
    return label_for_name(artist.surname or "", artist.givenname)


def _name_year_range_error(field: str, value: int | None) -> FieldError | None:
    if value is not None and not 1000 <= value <= 9999:
        return FieldError(field, "Muss eine vierstellige Jahreszahl sein.")
    return None


def _validate(
    db: Session, data: ArtistRequest, exclude_id: uuid.UUID | None
) -> list[FieldError]:
    errors: list[FieldError] = []

    length_error_msg = (
        f"Muss zwischen {_NAME_MIN_LENGTH} und {_NAME_MAX_LENGTH} Zeichen lang sein."
    )
    for field_name, value in (("surname", data.surname), ("givenname", data.givenname)):
        if not _NAME_MIN_LENGTH <= len(value) <= _NAME_MAX_LENGTH:
            errors.append(FieldError(field_name, length_error_msg))

    errors.extend(
        year_error
        for year_error in (
            _name_year_range_error("birthyear", data.birthyear),
            _name_year_range_error("deathyear", data.deathyear),
        )
        if year_error
    )

    stmt = select(Artist.id).where(
        func.lower(Artist.surname) == data.surname.lower(),
        func.lower(Artist.givenname) == data.givenname.lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(Artist.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        msg = "Die Kombination von Vor- und Nachname ist vergeben."
        errors.append(FieldError("surname", msg))
        errors.append(FieldError("givenname", msg))

    return errors


def _get_or_404(db: Session, artist_id: uuid.UUID) -> Artist:
    result = db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        raise ArtistNotFoundError
    return artist


def list_composer_artists(db: Session) -> Sequence[Artist]:
    """Dropdown source for Ordinariumwork/Propriumwork's "Komponist" select
    -- embedded directly in those entities' form payloads rather than
    gated by the artist maintain permission itself (see artistMaintain/
    ordinariumworkMaintain/propriumworkMaintain in permission_service.py,
    which share the identical planner/disponent condition)."""
    stmt = (
        select(Artist)
        .where(Artist.composer.is_(True))
        .order_by(Artist.surname, Artist.givenname)
    )
    return db.execute(stmt).scalars().all()


def search_artists(db: Session, query: str) -> Sequence[Artist]:
    """Filtered in the database (not in memory). Every whitespace-separated
    word in `query` must appear somewhere in "surname givenname"."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return []

    combined_name = func.lower(Artist.surname + " " + Artist.givenname)
    stmt = (
        select(Artist)
        .where(*[combined_name.like(f"%{word}%") for word in words])
        .order_by(Artist.surname, Artist.givenname)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    return db.execute(stmt).scalars().all()


def create_artist(db: Session, data: ArtistRequest) -> Artist:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise ArtistValidationError(errors)

    artist = Artist(
        surname=normalize_surname(data.surname),
        givenname=normalize_givenname(data.givenname),
        description=data.description,
        birthyear=data.birthyear,
        deathyear=data.deathyear,
        composer=data.composer,
        conductor=data.conductor,
    )
    db.add(artist)
    db.commit()
    return artist


def update_artist(db: Session, artist_id: uuid.UUID, data: ArtistRequest) -> Artist:
    artist = _get_or_404(db, artist_id)
    errors = _validate(db, data, exclude_id=artist_id)
    if errors:
        raise ArtistValidationError(errors)

    artist.surname = normalize_surname(data.surname)
    artist.givenname = normalize_givenname(data.givenname)
    artist.description = data.description
    artist.birthyear = data.birthyear
    artist.deathyear = data.deathyear
    artist.composer = data.composer
    artist.conductor = data.conductor
    db.commit()
    return artist


def get_artist(db: Session, artist_id: uuid.UUID) -> Artist:
    return _get_or_404(db, artist_id)


def _artist_has_dependencies(db: Session, artist_id: uuid.UUID) -> bool:
    # Ordinariumwork/Propriumwork's artist_id is the composer; Performance's
    # is the conductor (Dirigent) -- both point at the same `artists` table,
    # and either role counts as "in use" alike.
    for model in (Ordinariumwork, Propriumwork, Performance):
        count = db.execute(
            select(func.count()).select_from(model).where(model.artist_id == artist_id)
        ).scalar_one()
        if count > 0:
            return True
    return False


def delete_artist(db: Session, artist_id: uuid.UUID) -> None:
    artist = _get_or_404(db, artist_id)
    if _artist_has_dependencies(db, artist_id):
        raise ArtistInUseError
    db.delete(artist)
    db.commit()
