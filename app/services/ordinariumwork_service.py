from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select

from app.db.models.artist import Artist
from app.db.models.instrument import Instrument
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.ordinariumwork_position import OrdinariumworkPosition
from app.db.models.performance import Performance
from app.db.models.voice import Voice
from app.schemas.coreelement import CoreelementType
from app.schemas.ordinariumwork import (
    AvailablePositionOutput,
    OrdinariumworkAvailablePositionsOutput,
    OrdinariumworkPositionInput,
    OrdinariumworkPositionOutput,
    OrdinariumworkRequest,
    OrdinariumworkResponse,
    OrdinariumworkSearchResult,
    OrdinariumworkSetupOutput,
)
from app.services.artist_service import label_for
from app.services.coreelement_service import list_coreelements
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

_NAME_MIN_LENGTH = 3
_NAME_MAX_LENGTH = 60
_DURATION_MIN = 0
_DURATION_MAX = 999
_SEARCH_RESULT_LIMIT = 20
_NAME_LENGTH_ERROR = (
    f"Muss zwischen {_NAME_MIN_LENGTH} und {_NAME_MAX_LENGTH} Zeichen lang sein."
)

# Ordinariumwork positions are restricted to these two types
# (OrdinariumworkPosition structurally excludes 'choirjobs' -- it has no
# choirjob_id column at all). Narrower than
# app.services.position_types.PositionType (3-way), so kept local rather
# than importing/reusing that shared alias.
OrdinariumworkPositionType = Literal["instruments", "voices"]

_POSITION_MODELS: dict[OrdinariumworkPositionType, type[Instrument | Voice]] = {
    "instruments": Instrument,
    "voices": Voice,
}

_POSITION_COLUMN_NAMES: dict[OrdinariumworkPositionType, str] = {
    "instruments": "instrument_id",
    "voices": "voice_id",
}


def _position_kwargs(
    position_type: OrdinariumworkPositionType, position_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    """2-type counterpart of app.services.position_types.position_kwargs()
    for OrdinariumworkPosition's own instrument_id/voice_id-only shape."""
    return {_POSITION_COLUMN_NAMES[position_type]: position_id}


def _position_key(
    row: OrdinariumworkPosition,
) -> tuple[OrdinariumworkPositionType, uuid.UUID]:
    """2-type counterpart of app.services.position_types.position_key()."""
    if row.instrument_id is not None:
        return "instruments", row.instrument_id
    if row.voice_id is not None:
        return "voices", row.voice_id
    msg = "position row has neither instrument_id nor voice_id set"
    raise ValueError(msg)


_IN_USE_DETAIL = "Das Element kann nicht gelöscht werden, da es noch in Verwendung ist."


class OrdinariumworkNotFoundError(NotFoundError):
    """Raised when `ordinariumwork_id` doesn't exist."""


class OrdinariumworkValidationError(DomainValidationError):
    """Field-level validation failures, one (field, message) pair per
    failing field -- same pattern as auth_service.RegistrationConflictError."""


class OrdinariumworkInUseError(GeneralValidationError):
    """Raised when delete is blocked by a Performance referencing this
    Ordinariumwork."""

    def __init__(self) -> None:
        super().__init__(_IN_USE_DETAIL)


def _get_or_404(db: Session, ordinariumwork_id: uuid.UUID) -> Ordinariumwork:
    result = db.execute(
        select(Ordinariumwork).where(Ordinariumwork.id == ordinariumwork_id)
    )
    ordinariumwork = result.scalar_one_or_none()
    if ordinariumwork is None:
        raise OrdinariumworkNotFoundError
    return ordinariumwork


def _validate_positions(
    db: Session,
    items: list[OrdinariumworkPositionInput],
    position_type: OrdinariumworkPositionType,
) -> list[FieldError]:
    model = _POSITION_MODELS[position_type]
    errors: list[FieldError] = []
    seen_ids: set[uuid.UUID] = set()
    for item in items:
        if item.id in seen_ids:
            errors.append(FieldError("setup", f"{position_type}: doppelter Eintrag."))
            continue
        seen_ids.add(item.id)
        exists = db.execute(
            select(model.id).where(model.id == item.id)
        ).scalar_one_or_none()
        if exists is None:
            errors.append(
                FieldError("setup", f"{position_type}: Element nicht gefunden.")
            )
    return errors


def _validate(
    db: Session, data: OrdinariumworkRequest, exclude_id: uuid.UUID | None
) -> list[FieldError]:
    errors: list[FieldError] = []

    if not _NAME_MIN_LENGTH <= len(data.name) <= _NAME_MAX_LENGTH:
        errors.append(FieldError("name", _NAME_LENGTH_ERROR))

    if (
        db.execute(
            select(Artist.id).where(Artist.id == data.artist_id)
        ).scalar_one_or_none()
        is None
    ):
        errors.append(FieldError("artist_id", "Komponist/in wurde nicht gefunden."))

    if (
        data.duration is not None
        and not _DURATION_MIN <= data.duration <= _DURATION_MAX
    ):
        errors.append(
            FieldError(
                "duration", f"Muss zwischen {_DURATION_MIN} und {_DURATION_MAX} liegen."
            )
        )

    stmt = select(Ordinariumwork.id).where(
        func.lower(Ordinariumwork.name) == data.name.lower(),
        Ordinariumwork.artist_id == data.artist_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(Ordinariumwork.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        errors.append(
            FieldError(
                "name", "Dieses Werk ist für diesen Komponisten bereits erfasst."
            )
        )

    errors.extend(_validate_positions(db, data.setup.instruments, "instruments"))
    errors.extend(_validate_positions(db, data.setup.voices, "voices"))

    return errors


def _sync_positions(
    db: Session, ordinariumwork_id: uuid.UUID, data: OrdinariumworkRequest
) -> None:
    """Sync semantics: rows not in the new setup are removed, existing ones
    get their quantity updated, new ones are inserted."""
    existing = (
        db.execute(
            select(OrdinariumworkPosition).where(
                OrdinariumworkPosition.ordinariumwork_id == ordinariumwork_id
            )
        )
        .scalars()
        .all()
    )
    existing_by_key = {_position_key(p): p for p in existing}

    desired: dict[tuple[OrdinariumworkPositionType, uuid.UUID], int] = {}
    for item in data.setup.instruments:
        desired[("instruments", item.id)] = item.quantity
    for item in data.setup.voices:
        desired[("voices", item.id)] = item.quantity

    for key, position in existing_by_key.items():
        if key not in desired:
            db.delete(position)

    for (position_type, position_id), quantity in desired.items():
        existing_position = existing_by_key.get((position_type, position_id))
        if existing_position is not None:
            existing_position.quantity = quantity
        else:
            db.add(
                OrdinariumworkPosition(
                    ordinariumwork_id=ordinariumwork_id,
                    quantity=quantity,
                    **_position_kwargs(position_type, position_id),
                )
            )


def _to_response(db: Session, ordinariumwork: Ordinariumwork) -> OrdinariumworkResponse:
    artist = db.execute(
        select(Artist).where(Artist.id == ordinariumwork.artist_id)
    ).scalar_one_or_none()
    return OrdinariumworkResponse(
        id=ordinariumwork.id,
        name=ordinariumwork.name,
        description=ordinariumwork.description,
        artist_id=ordinariumwork.artist_id,
        artist_name=label_for(artist) if artist else "",
        duration=ordinariumwork.duration,
        demanding=ordinariumwork.demanding,
    )


def search_ordinariumworks(
    db: Session, query: str
) -> Sequence[OrdinariumworkSearchResult]:
    """Filtered and sorted in the database (not in memory): every
    whitespace-separated word in `query` must appear in the work's name or
    its artist's name."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return []

    combined = func.lower(
        Artist.surname + " " + Artist.givenname + " " + Ordinariumwork.name
    )
    stmt = (
        select(Ordinariumwork, Artist)
        .join(Artist, Ordinariumwork.artist_id == Artist.id)
        .where(*[combined.like(f"%{word}%") for word in words])
        .order_by(Artist.surname, Artist.givenname, Ordinariumwork.name)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    rows = db.execute(stmt).all()
    return [
        OrdinariumworkSearchResult(
            id=ordinariumwork.id, label=f"{label_for(artist)}: {ordinariumwork.name}"
        )
        for ordinariumwork, artist in rows
    ]


def get_available_positions(db: Session) -> OrdinariumworkAvailablePositionsOutput:
    """Instrument/Voice dropdown source for the setup editor -- gated by
    ordinariumworkMaintain, not instrumentMaintain/voiceMaintain (no
    cross-model authorization). Reuses coreelement_service's `order`-column
    ordering for consistency with the Coreelement admin pages."""
    instruments = list_coreelements(db, CoreelementType.instrument, active_only=True)
    voices = list_coreelements(db, CoreelementType.voice, active_only=True)
    return OrdinariumworkAvailablePositionsOutput(
        instruments=[
            AvailablePositionOutput(id=item.id, name=item.name) for item in instruments
        ],
        voices=[AvailablePositionOutput(id=item.id, name=item.name) for item in voices],
    )


def create_ordinariumwork(
    db: Session, data: OrdinariumworkRequest
) -> OrdinariumworkResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise OrdinariumworkValidationError(errors)

    ordinariumwork = Ordinariumwork(
        name=data.name,
        description=data.description,
        artist_id=data.artist_id,
        duration=data.duration,
        demanding=data.demanding,
    )
    db.add(ordinariumwork)
    db.flush()
    _sync_positions(db, ordinariumwork.id, data)
    db.commit()
    return _to_response(db, ordinariumwork)


def update_ordinariumwork(
    db: Session, ordinariumwork_id: uuid.UUID, data: OrdinariumworkRequest
) -> OrdinariumworkResponse:
    ordinariumwork = _get_or_404(db, ordinariumwork_id)
    errors = _validate(db, data, exclude_id=ordinariumwork_id)
    if errors:
        raise OrdinariumworkValidationError(errors)

    ordinariumwork.name = data.name
    ordinariumwork.description = data.description
    ordinariumwork.artist_id = data.artist_id
    ordinariumwork.duration = data.duration
    ordinariumwork.demanding = data.demanding
    _sync_positions(db, ordinariumwork_id, data)
    db.commit()
    return _to_response(db, ordinariumwork)


def get_ordinariumwork(
    db: Session, ordinariumwork_id: uuid.UUID
) -> OrdinariumworkResponse:
    ordinariumwork = _get_or_404(db, ordinariumwork_id)
    return _to_response(db, ordinariumwork)


def get_setup(db: Session, ordinariumwork_id: uuid.UUID) -> OrdinariumworkSetupOutput:
    """Output order follows the Instrument/Voice's own `order` column, not
    the id sequence or pivot-row insertion order."""
    _get_or_404(db, ordinariumwork_id)
    positions = (
        db.execute(
            select(OrdinariumworkPosition).where(
                OrdinariumworkPosition.ordinariumwork_id == ordinariumwork_id
            )
        )
        .scalars()
        .all()
    )

    quantity_by_key = {_position_key(p): p.quantity for p in positions}

    instruments_out: list[OrdinariumworkPositionOutput] = []
    voices_out: list[OrdinariumworkPositionOutput] = []
    for position_type, model, bucket in (
        ("instruments", Instrument, instruments_out),
        ("voices", Voice, voices_out),
    ):
        quantity_by_id = {
            item_id: quantity
            for (item_type, item_id), quantity in quantity_by_key.items()
            if item_type == position_type
        }
        if not quantity_by_id:
            continue
        items = (
            db.execute(
                select(model)
                .where(model.id.in_(quantity_by_id))
                .order_by(model.order, model.id)
            )
            .scalars()
            .all()
        )
        for item in items:
            bucket.append(
                OrdinariumworkPositionOutput(
                    id=item.id,
                    name=item.name,
                    quantity=quantity_by_id[item.id],
                    active=item.active,
                )
            )

    return OrdinariumworkSetupOutput(instruments=instruments_out, voices=voices_out)


def _ordinariumwork_has_dependencies(db: Session, ordinariumwork_id: uuid.UUID) -> bool:
    count = db.execute(
        select(func.count())
        .select_from(Performance)
        .where(Performance.ordinariumwork_id == ordinariumwork_id)
    ).scalar_one()
    return count > 0


def delete_ordinariumwork(db: Session, ordinariumwork_id: uuid.UUID) -> None:
    """Deleting the row alone is enough: `ordinariumwork_positions.
    ordinariumwork_id` is an ON DELETE CASCADE foreign key, so the
    database removes this Ordinariumwork's position rows on its own."""
    ordinariumwork = _get_or_404(db, ordinariumwork_id)
    if _ordinariumwork_has_dependencies(db, ordinariumwork_id):
        raise OrdinariumworkInUseError
    db.delete(ordinariumwork)
    db.commit()
