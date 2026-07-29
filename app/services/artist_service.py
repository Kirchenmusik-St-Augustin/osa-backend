from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.human_names import normalize_givenname, normalize_surname
from app.db.models.artist import Artist
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.propriumwork import Propriumwork
from app.schemas.artist import ArtistRequest

_NAME_MIN_LENGTH = 3
_NAME_MAX_LENGTH = 32
_SEARCH_RESULT_LIMIT = 20


class ArtistNotFoundError(Exception):
    """Raised when `artist_id` doesn't exist."""


class ArtistValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 auth_service.RegistrationConflictError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Artist validation failed")


class ArtistInUseError(Exception):
    """Raised when delete is blocked by a dependent Ordinariumwork/
    Propriumwork row -- mirrors Legacy's HasDependencies check. The third
    Legacy dependency (`performances`) doesn't exist in osa-backend yet
    (Schritt 5) and is added here once that domain lands."""


def label_for(artist: Artist) -> str:
    """Mirrors Legacy's HasHumanNames::name() virtual attribute
    ("SURNAME, Givenname"), used as the display label in search results
    and embedded in Ordinariumwork/Propriumwork responses."""
    if not artist.givenname:
        return artist.surname or ""
    return f"{artist.surname}, {artist.givenname}"


def _name_year_range_error(field: str, value: int | None) -> tuple[str, str] | None:
    if value is not None and not 1000 <= value <= 9999:
        return field, "Muss eine vierstellige Jahreszahl sein."
    return None


def _validate(
    db: Session, data: ArtistRequest, exclude_id: int | None
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []

    length_error_msg = (
        f"Muss zwischen {_NAME_MIN_LENGTH} und {_NAME_MAX_LENGTH} Zeichen lang sein."
    )
    for field_name, value in (("surname", data.surname), ("givenname", data.givenname)):
        if not _NAME_MIN_LENGTH <= len(value) <= _NAME_MAX_LENGTH:
            errors.append((field_name, length_error_msg))

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
        errors.append(("surname", msg))
        errors.append(("givenname", msg))

    return errors


def _get_or_404(db: Session, artist_id: int) -> Artist:
    result = db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        raise ArtistNotFoundError
    return artist


def list_composer_artists(db: Session) -> Sequence[Artist]:
    """Dropdown source for Ordinariumwork/Propriumwork's "Komponist" select
    -- mirrors Legacy's `Artist::ofType('composer')->get()`, which is
    embedded directly in those controllers' ShowForm resources rather than
    gated under ArtistController itself (see artistMaintain/
    ordinariumworkMaintain/propriumworkMaintain in permission_service.py,
    which share the identical planner/disponent condition)."""
    stmt = (
        select(Artist)
        .where(Artist.composer.is_(True))
        .order_by(Artist.surname, Artist.givenname)
    )
    return db.execute(stmt).scalars().all()


def search_artists(db: Session, query: str) -> Sequence[Artist]:
    """Real indexed-ish DB query, replacing Legacy's `Artist::search()`
    anti-pattern (loads the entire table into PHP, filters in memory).
    Every whitespace-separated word in `query` must appear somewhere in
    "surname givenname" (mirrors Legacy's `Str::containsAll` semantics)."""
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


def update_artist(db: Session, artist_id: int, data: ArtistRequest) -> Artist:
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


def get_artist(db: Session, artist_id: int) -> Artist:
    return _get_or_404(db, artist_id)


def _artist_has_dependencies(db: Session, artist_id: int) -> bool:
    for model in (Ordinariumwork, Propriumwork):
        count = db.execute(
            select(func.count()).select_from(model).where(model.artist_id == artist_id)
        ).scalar_one()
        if count > 0:
            return True
    return False


def delete_artist(db: Session, artist_id: int) -> None:
    artist = _get_or_404(db, artist_id)
    if _artist_has_dependencies(db, artist_id):
        raise ArtistInUseError
    db.delete(artist)
    db.commit()
