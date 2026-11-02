from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.models.artist import Artist
from app.schemas.base import IdLabelOutput
from app.services.artist_service import label_for
from app.services.errors import FieldError

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.db.models.repertoire_work_mixin import RepertoireWorkColumns

_NAME_MIN_LENGTH = 3
_NAME_MAX_LENGTH = 60
_DURATION_MIN = 1
_DURATION_MAX = 999
_SEARCH_RESULT_LIMIT = 20
_NAME_LENGTH_ERROR = (
    f"Muss zwischen {_NAME_MIN_LENGTH} und {_NAME_MAX_LENGTH} Zeichen lang sein."
)


@dataclass(frozen=True)
class WorkKind[ResponseT: BaseModel]:
    """What differs between the repertoire work tables that share the
    columns of `RepertoireWorkColumns`: the table itself and the shape of
    the response."""

    model: type[RepertoireWorkColumns]
    response_type: type[ResponseT]


def validate_work_fields[ResponseT: BaseModel](
    db: Session,
    kind: WorkKind[ResponseT],
    *,
    name: str,
    artist_id: uuid.UUID,
    duration: int | None,
    exclude_id: uuid.UUID | None,
) -> list[FieldError]:
    """Name length, existing artist, duration range and the case-insensitive
    duplicate check per artist (`exclude_id` skips the work being updated)."""
    errors: list[FieldError] = []

    if not _NAME_MIN_LENGTH <= len(name) <= _NAME_MAX_LENGTH:
        errors.append(FieldError("name", _NAME_LENGTH_ERROR))

    if (
        db.execute(select(Artist.id).where(Artist.id == artist_id)).scalar_one_or_none()
        is None
    ):
        errors.append(FieldError("artist_id", "Komponist/in wurde nicht gefunden."))

    if duration is not None and not _DURATION_MIN <= duration <= _DURATION_MAX:
        errors.append(
            FieldError(
                "duration", f"Muss zwischen {_DURATION_MIN} und {_DURATION_MAX} liegen."
            )
        )

    stmt = select(kind.model.id).where(
        func.lower(kind.model.name) == name.lower(),
        kind.model.artist_id == artist_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(kind.model.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        errors.append(
            FieldError(
                "name", "Dieses Werk ist für diesen Komponisten bereits erfasst."
            )
        )

    return errors


def search_works[ResponseT: BaseModel](
    db: Session, kind: WorkKind[ResponseT], query: str
) -> list[IdLabelOutput]:
    """Filtered and sorted in the database (not in memory): every
    whitespace-separated word in `query` must appear in the work's name or
    its artist's name."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return []

    combined = func.lower(
        Artist.surname + " " + Artist.givenname + " " + kind.model.name
    )
    stmt = (
        select(kind.model, Artist)
        .join(Artist, kind.model.artist_id == Artist.id)
        .where(*[combined.contains(word, autoescape=True) for word in words])
        .order_by(Artist.surname, Artist.givenname, kind.model.name)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    rows = db.execute(stmt).all()
    return [
        IdLabelOutput(id=work.id, label=f"{label_for(artist)}: {work.name}")
        for work, artist in rows
    ]


def work_response[ResponseT: BaseModel](
    db: Session, kind: WorkKind[ResponseT], work: RepertoireWorkColumns
) -> ResponseT:
    """One extra query for the artist's display name."""
    artist = db.execute(
        select(Artist).where(Artist.id == work.artist_id)
    ).scalar_one_or_none()
    return kind.response_type(
        id=work.id,
        name=work.name,
        description=work.description,
        artist_id=work.artist_id,
        artist_name=label_for(artist) if artist else "",
        duration=work.duration,
        demanding=work.demanding,
    )
