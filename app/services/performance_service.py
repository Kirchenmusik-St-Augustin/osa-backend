from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.datetime_utils import ensure_tz_aware
from app.db.models.artist import Artist
from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.performance_position import PerformancePosition
from app.db.models.performance_proprium import PerformanceProprium
from app.db.models.performance_rehearsal import PerformanceRehearsal
from app.db.models.propriumelement import Propriumelement
from app.db.models.propriumwork import Propriumwork
from app.db.models.voice import Voice
from app.schemas.coreelement import CoreelementType
from app.schemas.performance import (
    AvailablePositionOutput,
    PerformanceAvailableData,
    PerformanceCalendarItem,
    PerformanceFormData,
    PerformanceLocationOutput,
    PerformancePositionInput,
    PerformancePositionOutput,
    PerformancePropriumOutput,
    PerformanceRehearsalOutput,
    PerformanceRequest,
    PerformanceResponse,
    PerformanceSetupOutput,
    PerformanceShowResponse,
)
from app.services.artist_service import label_for
from app.services.coreelement_service import list_coreelements

_SCHEDULE_TOO_EARLY = "Aufführungs-Datum muss frühestens morgen sein."
_REHEARSAL_TOO_EARLY = "Proben-Datum muss frühestens morgen sein."
_REHEARSAL_AFTER_PERFORMANCE = "Proben-Datum muss vor Aufführungs-Datum liegen."
_LOCATION_HOUR_COLLISION = (
    "Die Kombination aus Aufführungs-Stunde und Ort muss eindeutig sein."
)
_LOCATION_HOUR_ARTIST_COLLISION = (
    "Die Kombination aus Aufführungs-Stunde, Ort und Dirigent muss eindeutig sein."
)

# Legacy's Relation::morphMap allows all three position types for
# Performance (unlike Ordinariumwork, which excludes choirjobs) -- see
# project_osa_performance_domain_research memory.
_POSITION_MODELS: dict[str, type[Instrument | Voice | Choirjob]] = {
    "instruments": Instrument,
    "voices": Voice,
    "choirjobs": Choirjob,
}


class PerformanceNotFoundError(Exception):
    """Raised when `performance_id` doesn't exist."""


class PerformanceValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 auth_service.RegistrationConflictError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Performance validation failed")


class PerformanceInPastError(Exception):
    """Raised when a maintain-type action (edit-data fetch, update, delete)
    is attempted on a performance whose schedule has already passed --
    mirrors PerformancePolicy::maintain()'s per-instance past-date lock,
    now enforced at fetch-time too, not just at save (User-Entscheidung
    2026-07-29, see project_osa_performance_domain_research memory)."""


def _get_or_404(db: Session, performance_id: int) -> Performance:
    result = db.execute(select(Performance).where(Performance.id == performance_id))
    performance = result.scalar_one_or_none()
    if performance is None:
        raise PerformanceNotFoundError
    return performance


def _ensure_not_past(performance: Performance) -> None:
    if ensure_tz_aware(performance.schedule) < datetime.now(UTC):
        raise PerformanceInPastError


def _tomorrow_start() -> datetime:
    now = datetime.now(UTC)
    return datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)


def _validate_positions(
    db: Session, items: list[PerformancePositionInput], position_type: str
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


def _validate_proprium(db: Session, data: PerformanceRequest) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    seen_elements: set[int] = set()
    for entry in data.proprium:
        if entry.propriumelement_id in seen_elements:
            errors.append(("proprium", "Doppelter Eintrag für dasselbe Element."))
            continue
        seen_elements.add(entry.propriumelement_id)
        if (
            db.execute(
                select(Propriumelement.id).where(
                    Propriumelement.id == entry.propriumelement_id
                )
            ).scalar_one_or_none()
            is None
        ):
            errors.append(("proprium", "Element wurde nicht gefunden."))
        if (
            db.execute(
                select(Propriumwork.id).where(Propriumwork.id == entry.propriumwork_id)
            ).scalar_one_or_none()
            is None
        ):
            errors.append(("proprium", "Werk wurde nicht gefunden."))
    return errors


def _validate_rehearsals(data: PerformanceRequest) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    tomorrow_start = _tomorrow_start()
    schedule = ensure_tz_aware(data.schedule)
    for rehearsal in data.rehearsals:
        rehearsal_schedule = ensure_tz_aware(rehearsal.schedule)
        if rehearsal_schedule < tomorrow_start:
            errors.append(("rehearsals", _REHEARSAL_TOO_EARLY))
        if rehearsal_schedule > schedule:
            errors.append(("rehearsals", _REHEARSAL_AFTER_PERFORMANCE))
    return errors


def _validate_collision(
    db: Session, data: PerformanceRequest, exclude_id: int | None
) -> list[tuple[str, str]]:
    """Legacy truncates to the HOUR (not the DB's exact-timestamp unique
    indexes) and, per User-Entscheidung 2026-07-29, now runs on both
    create AND update (Legacy itself only ran this on create -- a real gap,
    fixed here, see project_osa_performance_domain_research memory)."""
    schedule = ensure_tz_aware(data.schedule)
    hour_start = schedule.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)

    stmt = select(Performance).where(Performance.location_id == data.location_id)
    if exclude_id is not None:
        stmt = stmt.where(Performance.id != exclude_id)
    same_location = db.execute(stmt).scalars().all()
    same_hour = [
        performance
        for performance in same_location
        if hour_start <= ensure_tz_aware(performance.schedule) < hour_end
    ]

    errors: list[tuple[str, str]] = []
    if same_hour:
        errors.append(("schedule", _LOCATION_HOUR_COLLISION))
    if any(performance.artist_id == data.artist_id for performance in same_hour):
        errors.append(("schedule", _LOCATION_HOUR_ARTIST_COLLISION))
    return errors


def _validate(
    db: Session, data: PerformanceRequest, exclude_id: int | None
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    schedule = ensure_tz_aware(data.schedule)

    if schedule < _tomorrow_start():
        errors.append(("schedule", _SCHEDULE_TOO_EARLY))

    if (
        db.execute(
            select(Location.id).where(Location.id == data.location_id)
        ).scalar_one_or_none()
        is None
    ):
        errors.append(("location_id", "Ort wurde nicht gefunden."))

    if (
        db.execute(
            select(Ordinariumwork.id).where(Ordinariumwork.id == data.ordinariumwork_id)
        ).scalar_one_or_none()
        is None
    ):
        errors.append(
            ("ordinariumwork_id", "Ordinarium-Komposition wurde nicht gefunden.")
        )

    if (
        data.artist_id is not None
        and db.execute(
            select(Artist.id).where(Artist.id == data.artist_id)
        ).scalar_one_or_none()
        is None
    ):
        errors.append(("artist_id", "Dirigent wurde nicht gefunden."))

    errors.extend(_validate_positions(db, data.setup.instruments, "instruments"))
    errors.extend(_validate_positions(db, data.setup.voices, "voices"))
    errors.extend(_validate_positions(db, data.setup.choirjobs, "choirjobs"))
    errors.extend(_validate_proprium(db, data))
    errors.extend(_validate_rehearsals(data))
    errors.extend(_validate_collision(db, data, exclude_id))

    return errors


def _sync_positions(db: Session, performance_id: int, data: PerformanceRequest) -> None:
    existing = (
        db.execute(
            select(PerformancePosition).where(
                PerformancePosition.performance_id == performance_id
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
    for item in data.setup.choirjobs:
        desired[("choirjobs", item.id)] = item.quantity

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
                PerformancePosition(
                    performance_id=performance_id,
                    position_type=position_type,
                    position_id=position_id,
                    quantity=quantity,
                    created_at=now,
                    updated_at=now,
                )
            )


def _sync_proprium(db: Session, performance_id: int, data: PerformanceRequest) -> None:
    existing = (
        db.execute(
            select(PerformanceProprium).where(
                PerformanceProprium.performance_id == performance_id
            )
        )
        .scalars()
        .all()
    )
    existing_by_element = {p.propriumelement_id: p for p in existing}
    desired = {
        entry.propriumelement_id: entry.propriumwork_id for entry in data.proprium
    }

    for element_id, row in existing_by_element.items():
        if element_id not in desired:
            db.delete(row)

    now = datetime.now(UTC)
    for element_id, propriumwork_id in desired.items():
        row = existing_by_element.get(element_id)
        if row is not None:
            row.propriumwork_id = propriumwork_id
            row.updated_at = now
        else:
            db.add(
                PerformanceProprium(
                    performance_id=performance_id,
                    propriumelement_id=element_id,
                    propriumwork_id=propriumwork_id,
                    created_at=now,
                    updated_at=now,
                )
            )


def _sync_rehearsals(
    db: Session, performance_id: int, data: PerformanceRequest
) -> None:
    """Legacy always fully replaces rehearsals (delete-all, recreate) on
    every save, never diffs them -- 1:1 replicated, including the
    dedup-by-schedule (Legacy: `->unique('schedule')` before createMany)."""
    db.execute(
        delete(PerformanceRehearsal).where(
            PerformanceRehearsal.performance_id == performance_id
        )
    )
    now = datetime.now(UTC)
    seen_schedules: set[datetime] = set()
    for rehearsal in data.rehearsals:
        schedule = ensure_tz_aware(rehearsal.schedule)
        if schedule in seen_schedules:
            continue
        seen_schedules.add(schedule)
        db.add(
            PerformanceRehearsal(
                performance_id=performance_id,
                schedule=schedule,
                comment=rehearsal.comment,
                created_at=now,
                updated_at=now,
            )
        )


def _location_output(location: Location) -> PerformanceLocationOutput:
    return PerformanceLocationOutput(
        id=location.id,
        name=location.name,
        color=location.color,
        address=location.address,
    )


def _to_response(performance: Performance) -> PerformanceResponse:
    return PerformanceResponse(
        id=performance.id,
        schedule=performance.schedule,
        location_id=performance.location_id,
        ordinariumwork_id=performance.ordinariumwork_id,
        artist_id=performance.artist_id,
        description=performance.description,
        choirjob_defaultfee=performance.choirjob_defaultfee,
        instrument_defaultfee=performance.instrument_defaultfee,
        voice_defaultfee=performance.voice_defaultfee,
        extracost_amount=performance.extracost_amount,
        extracost_description=performance.extracost_description,
    )


def get_setup(db: Session, performance_id: int) -> PerformanceSetupOutput:
    """Output order follows each Instrument/Voice/Choirjob's own `order`
    column (their shared global admin-managed ordering), not pivot-row
    insertion order -- same lesson as Ordinariumwork's setup(), confirmed
    live to apply here too (see project_osa_performance_domain_research
    memory)."""
    positions = (
        db.execute(
            select(PerformancePosition).where(
                PerformancePosition.performance_id == performance_id
            )
        )
        .scalars()
        .all()
    )

    instruments_out: list[PerformancePositionOutput] = []
    voices_out: list[PerformancePositionOutput] = []
    choirjobs_out: list[PerformancePositionOutput] = []
    for position_type, model, bucket in (
        ("instruments", Instrument, instruments_out),
        ("voices", Voice, voices_out),
        ("choirjobs", Choirjob, choirjobs_out),
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
                PerformancePositionOutput(
                    id=item.id, name=item.name, quantity=quantity_by_id[item.id]
                )
            )

    return PerformanceSetupOutput(
        instruments=instruments_out, voices=voices_out, choirjobs=choirjobs_out
    )


def _build_proprium_by_performance(
    db: Session, performance_ids: list[int]
) -> dict[int, list[PerformancePropriumOutput]]:
    """Batched across a whole list of performances -- an N+1-safe building
    block for both the single-performance get_proprium() below and the
    calendar's list_performances_for_month() (CLAUDE.md testing_constraints:
    query count must not scale with the number of performances returned)."""
    result: dict[int, list[PerformancePropriumOutput]] = {
        pid: [] for pid in performance_ids
    }
    if not performance_ids:
        return result

    entries = (
        db.execute(
            select(PerformanceProprium).where(
                PerformanceProprium.performance_id.in_(performance_ids)
            )
        )
        .scalars()
        .all()
    )
    if not entries:
        return result

    element_ids = {e.propriumelement_id for e in entries}
    work_ids = {e.propriumwork_id for e in entries}
    elements_by_id = {
        el.id: el
        for el in db.execute(
            select(Propriumelement).where(Propriumelement.id.in_(element_ids))
        )
        .scalars()
        .all()
    }
    works_by_id = {
        w.id: w
        for w in db.execute(select(Propriumwork).where(Propriumwork.id.in_(work_ids)))
        .scalars()
        .all()
    }
    artist_ids = {w.artist_id for w in works_by_id.values()}
    artists_by_id = (
        {
            a.id: a
            for a in db.execute(select(Artist).where(Artist.id.in_(artist_ids)))
            .scalars()
            .all()
        }
        if artist_ids
        else {}
    )

    entries_by_performance: dict[int, list[PerformanceProprium]] = {}
    for entry in entries:
        entries_by_performance.setdefault(entry.performance_id, []).append(entry)

    for performance_id, perf_entries in entries_by_performance.items():
        ordered = sorted(
            (
                entry
                for entry in perf_entries
                if entry.propriumelement_id in elements_by_id
            ),
            key=lambda entry: (
                elements_by_id[entry.propriumelement_id].order,
                elements_by_id[entry.propriumelement_id].id,
            ),
        )
        outputs: list[PerformancePropriumOutput] = []
        for entry in ordered:
            element = elements_by_id[entry.propriumelement_id]
            work = works_by_id.get(entry.propriumwork_id)
            if work is None:
                continue
            artist = artists_by_id.get(work.artist_id)
            outputs.append(
                PerformancePropriumOutput(
                    propriumelement_id=element.id,
                    propriumelement_name=element.name,
                    propriumwork_id=work.id,
                    propriumwork_name=work.name,
                    artist_name=label_for(artist) if artist else "",
                    description=work.description,
                    demanding=work.demanding,
                )
            )
        result[performance_id] = outputs

    return result


def get_proprium(db: Session, performance_id: int) -> list[PerformancePropriumOutput]:
    return _build_proprium_by_performance(db, [performance_id]).get(performance_id, [])


def _build_rehearsals_by_performance(
    db: Session, performance_ids: list[int]
) -> dict[int, list[PerformanceRehearsalOutput]]:
    result: dict[int, list[PerformanceRehearsalOutput]] = {
        pid: [] for pid in performance_ids
    }
    if not performance_ids:
        return result
    rehearsals = (
        db.execute(
            select(PerformanceRehearsal)
            .where(PerformanceRehearsal.performance_id.in_(performance_ids))
            .order_by(PerformanceRehearsal.schedule)
        )
        .scalars()
        .all()
    )
    for rehearsal in rehearsals:
        result[rehearsal.performance_id].append(
            PerformanceRehearsalOutput(
                schedule=rehearsal.schedule, comment=rehearsal.comment
            )
        )
    return result


def get_rehearsals(
    db: Session, performance_id: int
) -> list[PerformanceRehearsalOutput]:
    return _build_rehearsals_by_performance(db, [performance_id]).get(
        performance_id, []
    )


def list_performances_for_month(
    db: Session, year: int, month: int
) -> Sequence[PerformanceCalendarItem]:
    """Real indexed DB query (SQLite `strftime`), mirroring Legacy's own
    `Performance::ofMonth()` (already a real query there, not an
    anti-pattern to fix) -- relies on `schedule` always being written as a
    UTC-normalized, offset-free string (see ensure_tz_aware/datetime.now(UTC)
    convention), so a plain '%Y-%m' prefix match is reliable."""
    month_str = f"{year:04d}-{month:02d}"
    performances = (
        db.execute(
            select(Performance)
            .where(func.strftime("%Y-%m", Performance.schedule) == month_str)
            .order_by(Performance.schedule)
        )
        .scalars()
        .all()
    )
    if not performances:
        return []

    performance_ids = [p.id for p in performances]
    location_ids = {p.location_id for p in performances}
    ordinariumwork_ids = {p.ordinariumwork_id for p in performances}
    artist_ids = {p.artist_id for p in performances if p.artist_id is not None}

    locations_by_id = {
        location.id: location
        for location in db.execute(
            select(Location).where(Location.id.in_(location_ids))
        )
        .scalars()
        .all()
    }
    ordinariumworks_by_id = {
        work.id: work
        for work in db.execute(
            select(Ordinariumwork).where(Ordinariumwork.id.in_(ordinariumwork_ids))
        )
        .scalars()
        .all()
    }
    artists_by_id = (
        {
            artist.id: artist
            for artist in db.execute(select(Artist).where(Artist.id.in_(artist_ids)))
            .scalars()
            .all()
        }
        if artist_ids
        else {}
    )
    proprium_by_performance = _build_proprium_by_performance(db, performance_ids)
    rehearsals_by_performance = _build_rehearsals_by_performance(db, performance_ids)

    items: list[PerformanceCalendarItem] = []
    for performance in performances:
        location = locations_by_id[performance.location_id]
        ordinariumwork = ordinariumworks_by_id[performance.ordinariumwork_id]
        artist = (
            artists_by_id.get(performance.artist_id) if performance.artist_id else None
        )
        proprium = proprium_by_performance.get(performance.id, [])
        items.append(
            PerformanceCalendarItem(
                id=performance.id,
                schedule=performance.schedule,
                location=_location_output(location),
                ordinariumwork_id=ordinariumwork.id,
                ordinariumwork_name=ordinariumwork.name,
                ordinariumwork_demanding=ordinariumwork.demanding,
                artist_name=label_for(artist) if artist else None,
                proprium=proprium,
                demanding_proprium=any(entry.demanding for entry in proprium),
                rehearsals=rehearsals_by_performance.get(performance.id, []),
            )
        )
    return items


def get_performance_detail(db: Session, performance_id: int) -> PerformanceShowResponse:
    performance = _get_or_404(db, performance_id)
    location = db.execute(
        select(Location).where(Location.id == performance.location_id)
    ).scalar_one()
    ordinariumwork = db.execute(
        select(Ordinariumwork).where(Ordinariumwork.id == performance.ordinariumwork_id)
    ).scalar_one()
    artist = (
        db.execute(
            select(Artist).where(Artist.id == performance.artist_id)
        ).scalar_one_or_none()
        if performance.artist_id is not None
        else None
    )
    proprium = get_proprium(db, performance_id)

    return PerformanceShowResponse(
        id=performance.id,
        schedule=performance.schedule,
        location=_location_output(location),
        ordinariumwork_id=ordinariumwork.id,
        ordinariumwork_name=ordinariumwork.name,
        ordinariumwork_description=ordinariumwork.description,
        ordinariumwork_demanding=ordinariumwork.demanding,
        artist_id=performance.artist_id,
        artist_name=label_for(artist) if artist else None,
        artist_description=artist.description if artist else None,
        description=performance.description,
        rehearsals=get_rehearsals(db, performance_id),
        setup=get_setup(db, performance_id),
        proprium=proprium,
        demanding_proprium=any(entry.demanding for entry in proprium),
    )


def get_form_data(db: Session, performance_id: int) -> PerformanceFormData:
    performance = _get_or_404(db, performance_id)
    _ensure_not_past(performance)
    ordinariumwork = db.execute(
        select(Ordinariumwork).where(Ordinariumwork.id == performance.ordinariumwork_id)
    ).scalar_one()
    composer = db.execute(
        select(Artist).where(Artist.id == ordinariumwork.artist_id)
    ).scalar_one_or_none()
    ordinariumwork_label = (
        f"{label_for(composer)}: {ordinariumwork.name}"
        if composer
        else ordinariumwork.name
    )

    return PerformanceFormData(
        id=performance.id,
        schedule=performance.schedule,
        location_id=performance.location_id,
        ordinariumwork_id=performance.ordinariumwork_id,
        ordinariumwork_label=ordinariumwork_label,
        artist_id=performance.artist_id,
        description=performance.description,
        choirjob_defaultfee=performance.choirjob_defaultfee,
        instrument_defaultfee=performance.instrument_defaultfee,
        voice_defaultfee=performance.voice_defaultfee,
        extracost_amount=performance.extracost_amount,
        extracost_description=performance.extracost_description,
        setup=get_setup(db, performance_id),
        proprium=get_proprium(db, performance_id),
        rehearsals=get_rehearsals(db, performance_id),
        # Booking domain (Schritt 6) doesn't exist in osa-backend yet -- the
        # only current block on deletion is the past-lock above, which
        # already raised if this performance were past.
        deletable=True,
    )


def get_available_data(db: Session) -> PerformanceAvailableData:
    conductors = (
        db.execute(
            select(Artist)
            .where(Artist.conductor.is_(True))
            .order_by(Artist.surname, Artist.givenname)
        )
        .scalars()
        .all()
    )
    instruments = list_coreelements(db, CoreelementType.instrument)
    voices = list_coreelements(db, CoreelementType.voice)
    choirjobs = list_coreelements(db, CoreelementType.choirjob)
    propriumelements = list_coreelements(db, CoreelementType.propriumelement)
    locations = (
        db.execute(select(Location).order_by(Location.order, Location.id))
        .scalars()
        .all()
    )

    return PerformanceAvailableData(
        conductors=[
            AvailablePositionOutput(id=a.id, name=label_for(a)) for a in conductors
        ],
        instruments=[
            AvailablePositionOutput(id=i.id, name=i.name) for i in instruments
        ],
        voices=[AvailablePositionOutput(id=v.id, name=v.name) for v in voices],
        choirjobs=[AvailablePositionOutput(id=c.id, name=c.name) for c in choirjobs],
        locations=[_location_output(location) for location in locations],
        propriumelements=[
            AvailablePositionOutput(id=p.id, name=p.name) for p in propriumelements
        ],
    )


def create_performance(db: Session, data: PerformanceRequest) -> PerformanceResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise PerformanceValidationError(errors)

    now = datetime.now(UTC)
    performance = Performance(
        schedule=ensure_tz_aware(data.schedule),
        location_id=data.location_id,
        ordinariumwork_id=data.ordinariumwork_id,
        artist_id=data.artist_id,
        description=data.description,
        choirjob_defaultfee=data.choirjob_defaultfee,
        instrument_defaultfee=data.instrument_defaultfee,
        voice_defaultfee=data.voice_defaultfee,
        extracost_amount=data.extracost_amount,
        extracost_description=data.extracost_description,
        created_at=now,
        updated_at=now,
    )
    db.add(performance)
    db.flush()
    _sync_positions(db, performance.id, data)
    _sync_proprium(db, performance.id, data)
    _sync_rehearsals(db, performance.id, data)
    db.commit()
    return _to_response(performance)


def update_performance(
    db: Session, performance_id: int, data: PerformanceRequest
) -> PerformanceResponse:
    performance = _get_or_404(db, performance_id)
    _ensure_not_past(performance)
    errors = _validate(db, data, exclude_id=performance_id)
    if errors:
        raise PerformanceValidationError(errors)

    performance.schedule = ensure_tz_aware(data.schedule)
    performance.location_id = data.location_id
    performance.ordinariumwork_id = data.ordinariumwork_id
    performance.artist_id = data.artist_id
    performance.description = data.description
    performance.choirjob_defaultfee = data.choirjob_defaultfee
    performance.instrument_defaultfee = data.instrument_defaultfee
    performance.voice_defaultfee = data.voice_defaultfee
    performance.extracost_amount = data.extracost_amount
    performance.extracost_description = data.extracost_description
    performance.updated_at = datetime.now(UTC)
    _sync_positions(db, performance_id, data)
    _sync_proprium(db, performance_id, data)
    _sync_rehearsals(db, performance_id, data)
    db.commit()
    return _to_response(performance)


def delete_performance(db: Session, performance_id: int) -> None:
    # Legacy's HasDependencies target for Performance (bookings/
    # booking_requests) doesn't exist in osa-backend yet (Schritt 6) --
    # delete is unconditional (besides the past-lock) until that domain
    # lands, mirroring the Ordinariumwork/Propriumwork precedent from
    # Schritt 4.
    performance = _get_or_404(db, performance_id)
    _ensure_not_past(performance)
    db.execute(
        delete(PerformancePosition).where(
            PerformancePosition.performance_id == performance_id
        )
    )
    db.execute(
        delete(PerformanceProprium).where(
            PerformanceProprium.performance_id == performance_id
        )
    )
    db.execute(
        delete(PerformanceRehearsal).where(
            PerformanceRehearsal.performance_id == performance_id
        )
    )
    db.delete(performance)
    db.commit()
