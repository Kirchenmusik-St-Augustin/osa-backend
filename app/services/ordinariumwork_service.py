from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

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

_NAME_MIN_LENGTH = 3
_NAME_MAX_LENGTH = 60
_DURATION_MIN = 0
_DURATION_MAX = 999
_SEARCH_RESULT_LIMIT = 20
_NAME_LENGTH_ERROR = (
    f"Muss zwischen {_NAME_MIN_LENGTH} und {_NAME_MAX_LENGTH} Zeichen lang sein."
)

# Legacy's Relation::morphMap restricts Ordinariumwork positions to these
# two types (the DB CHECK constraint on ordinariumwork_positions.position_type
# excludes 'choirjobs' -- confirmed by 1677 live rows, zero choirjobs, see
# project_osa_legacy_domain_map memory).
_POSITION_MODELS: dict[str, type[Instrument | Voice]] = {
    "instruments": Instrument,
    "voices": Voice,
}


class OrdinariumworkNotFoundError(Exception):
    """Raised when `ordinariumwork_id` doesn't exist."""


class OrdinariumworkValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 auth_service.RegistrationConflictError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Ordinariumwork validation failed")


class OrdinariumworkInUseError(Exception):
    """Raised when delete is blocked by a Performance referencing this
    Ordinariumwork -- Legacy's only HasDependencies target (`performances`),
    retrofitted now that Schritt 5 built that domain (was deferred before,
    mirroring the Instrument/Voice retrofit in coreelement_service.py)."""


def _get_or_404(db: Session, ordinariumwork_id: int) -> Ordinariumwork:
    result = db.execute(
        select(Ordinariumwork).where(Ordinariumwork.id == ordinariumwork_id)
    )
    ordinariumwork = result.scalar_one_or_none()
    if ordinariumwork is None:
        raise OrdinariumworkNotFoundError
    return ordinariumwork


def _validate_positions(
    db: Session, items: list[OrdinariumworkPositionInput], position_type: str
) -> list[tuple[str, str]]:
    model = _POSITION_MODELS[position_type]
    errors: list[tuple[str, str]] = []
    seen_ids: set[int] = set()
    for item in items:
        if item.id in seen_ids:
            errors.append(("setup", f"{position_type}: doppelter Eintrag."))
            continue
        seen_ids.add(item.id)
        exists = db.execute(
            select(model.id).where(model.id == item.id)
        ).scalar_one_or_none()
        if exists is None:
            errors.append(("setup", f"{position_type}: Element nicht gefunden."))
    return errors


def _validate(
    db: Session, data: OrdinariumworkRequest, exclude_id: int | None
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

    stmt = select(Ordinariumwork.id).where(
        func.lower(Ordinariumwork.name) == data.name.lower(),
        Ordinariumwork.artist_id == data.artist_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(Ordinariumwork.id != exclude_id)
    if db.execute(stmt).scalar_one_or_none() is not None:
        errors.append(
            ("name", "Dieses Werk ist für diesen Komponisten bereits erfasst.")
        )

    errors.extend(_validate_positions(db, data.setup.instruments, "instruments"))
    errors.extend(_validate_positions(db, data.setup.voices, "voices"))

    return errors


def _sync_positions(
    db: Session, ordinariumwork_id: int, data: OrdinariumworkRequest
) -> None:
    """Mirrors Legacy's `Ordinariumwork::setup()` sync() semantics: rows
    not in the new setup are removed, existing ones get their quantity
    updated, new ones are inserted."""
    existing = (
        db.execute(
            select(OrdinariumworkPosition).where(
                OrdinariumworkPosition.ordinariumwork_id == ordinariumwork_id
            )
        )
        .scalars()
        .all()
    )
    existing_by_key = {(p.position_type, p.position_id): p for p in existing}

    desired: dict[tuple[str, int], int] = {}
    for item in data.setup.instruments:
        desired[("instruments", item.id)] = item.quantity
    for item in data.setup.voices:
        desired[("voices", item.id)] = item.quantity

    for key, position in existing_by_key.items():
        if key not in desired:
            db.delete(position)

    now = datetime.now(UTC)
    for (position_type, position_id), quantity in desired.items():
        existing_position = existing_by_key.get((position_type, position_id))
        if existing_position is not None:
            existing_position.quantity = quantity
            existing_position.updated_at = now
        else:
            db.add(
                OrdinariumworkPosition(
                    ordinariumwork_id=ordinariumwork_id,
                    position_type=position_type,
                    position_id=position_id,
                    quantity=quantity,
                    created_at=now,
                    updated_at=now,
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
    """Real indexed-ish DB query, replacing Legacy's
    `Ordinariumwork::search()` anti-pattern (loads the entire table into
    PHP, filters in memory, then a dead `sortBy('artist_name')` call that
    never actually sorted since that attribute doesn't exist on the model
    -- an obvious oversight, corrected here with a real ORDER BY instead
    of replicated verbatim)."""
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
    """Instrument/Voice dropdown source for the setup editor -- mirrors
    Legacy's `Instrument::all()`/`Voice::all()` embedded directly in
    Ordinariumwork's ShowForm resource (gated by ordinariumworkMaintain,
    not instrumentMaintain/voiceMaintain -- Legacy performs zero
    cross-model authorization here). Reuses coreelement_service's
    `order`-column ordering for consistency with the Coreelement admin
    pages (Schritt 3)."""
    instruments = list_coreelements(db, CoreelementType.instrument)
    voices = list_coreelements(db, CoreelementType.voice)
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

    now = datetime.now(UTC)
    ordinariumwork = Ordinariumwork(
        name=data.name,
        description=data.description,
        artist_id=data.artist_id,
        duration=data.duration,
        demanding=data.demanding,
        created_at=now,
        updated_at=now,
    )
    db.add(ordinariumwork)
    db.flush()
    _sync_positions(db, ordinariumwork.id, data)
    db.commit()
    return _to_response(db, ordinariumwork)


def update_ordinariumwork(
    db: Session, ordinariumwork_id: int, data: OrdinariumworkRequest
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
    ordinariumwork.updated_at = datetime.now(UTC)
    _sync_positions(db, ordinariumwork_id, data)
    db.commit()
    return _to_response(db, ordinariumwork)


def get_ordinariumwork(db: Session, ordinariumwork_id: int) -> OrdinariumworkResponse:
    ordinariumwork = _get_or_404(db, ordinariumwork_id)
    return _to_response(db, ordinariumwork)


def get_setup(db: Session, ordinariumwork_id: int) -> OrdinariumworkSetupOutput:
    """Output order follows the Instrument/Voice's own `order` column, not
    pivot-row insertion order -- Legacy's Instrument/Voice models carry a
    global `OrderByOrder` scope (HasCoreelementFeatures trait) that applies
    to EVERY query against them, including the `morphedByMany` relation
    query behind `Ordinariumwork::setup()`. Confirmed live against
    production data (2026-07-29): a real Ordinariumwork's Instrumente table
    showed Konzertmeister/Violine 1/Violine 2/Violoncello/Contrabass/Orgel
    in exactly their coreelement `order` sequence (0/1/2/4/6/31), not their
    `id` sequence (18/35/2/4/5/1, unrelated) or pivot-row insertion order."""
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

    instruments_out: list[OrdinariumworkPositionOutput] = []
    voices_out: list[OrdinariumworkPositionOutput] = []
    for position_type, model, bucket in (
        ("instruments", Instrument, instruments_out),
        ("voices", Voice, voices_out),
    ):
        quantity_by_id = {
            p.position_id: p.quantity
            for p in positions
            if p.position_type == position_type
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
                    id=item.id, name=item.name, quantity=quantity_by_id[item.id]
                )
            )

    return OrdinariumworkSetupOutput(instruments=instruments_out, voices=voices_out)


def _ordinariumwork_has_dependencies(db: Session, ordinariumwork_id: int) -> bool:
    count = db.execute(
        select(func.count())
        .select_from(Performance)
        .where(Performance.ordinariumwork_id == ordinariumwork_id)
    ).scalar_one()
    return count > 0


def delete_ordinariumwork(db: Session, ordinariumwork_id: int) -> None:
    ordinariumwork = _get_or_404(db, ordinariumwork_id)
    if _ordinariumwork_has_dependencies(db, ordinariumwork_id):
        raise OrdinariumworkInUseError
    db.execute(
        delete(OrdinariumworkPosition).where(
            OrdinariumworkPosition.ordinariumwork_id == ordinariumwork_id
        )
    )
    db.delete(ordinariumwork)
    db.commit()
