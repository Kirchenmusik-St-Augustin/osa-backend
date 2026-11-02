import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.datetime_utils import local_now
from app.core.security import get_password_hash
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.user import User
from app.db.models.voice import Voice
from app.schemas.artist import ArtistRequest
from app.schemas.performance import (
    PerformancePositionInput,
    PerformanceRequest,
    PerformanceSetupInput,
)
from app.services import artist_service, performance_service
from tests.user_positions import create_user_position

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_schedule_counter = itertools.count(2)


_id_counter = itertools.count(700_000)


def unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def unique_id() -> int:
    return next(_id_counter)


def unique_schedule() -> datetime:
    days_ahead = next(_schedule_counter)
    base = local_now() + timedelta(days=days_ahead)
    return base.replace(minute=0, second=0, microsecond=0)


def create_location(db_session: Session) -> Location:
    now = datetime.now(UTC)
    location = Location(
        name=unique("Location"),
        order=0,
        address="Adresse 1",
        color="000000",
        created_at=now,
        updated_at=now,
    )
    db_session.add(location)
    db_session.commit()
    return location


def create_ordinariumwork(db_session: Session, composer_id: int) -> Ordinariumwork:
    now = datetime.now(UTC)
    work = Ordinariumwork(
        name=unique("Werk"),
        artist_id=composer_id,
        demanding=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add(work)
    db_session.commit()
    return work


def create_instrument(db_session: Session) -> Instrument:
    now = datetime.now(UTC)
    instrument = Instrument(
        name=unique("Instrument"), order=0, created_at=now, updated_at=now
    )
    db_session.add(instrument)
    db_session.commit()
    return instrument


def create_voice(db_session: Session, *, order: int = 0) -> Voice:
    now = datetime.now(UTC)
    voice = Voice(name=unique("Voice"), order=order, created_at=now, updated_at=now)
    db_session.add(voice)
    db_session.commit()
    return voice


def create_choirjob(db_session: Session) -> Choirjob:
    now = datetime.now(UTC)
    choirjob = Choirjob(
        name=unique("Choirjob"), order=0, created_at=now, updated_at=now
    )
    db_session.add(choirjob)
    db_session.commit()
    return choirjob


def create_performance(
    db_session: Session,
    *,
    instruments: dict[int, int] | None = None,
    voices: dict[int, int] | None = None,
    choirjobs: dict[int, int] | None = None,
    schedule: datetime | None = None,
    extracost_amount: int | None = None,
    extracost_description: str | None = None,
) -> int:
    composer = artist_service.create_artist(
        db_session,
        ArtistRequest(surname=unique("Composer"), givenname="Given", composer=True),
    )
    location = create_location(db_session)
    work = create_ordinariumwork(db_session, composer.id)
    setup = PerformanceSetupInput(
        instruments=[
            PerformancePositionInput(id=i, quantity=q)
            for i, q in (instruments or {}).items()
        ],
        voices=[
            PerformancePositionInput(id=i, quantity=q)
            for i, q in (voices or {}).items()
        ],
        choirjobs=[
            PerformancePositionInput(id=i, quantity=q)
            for i, q in (choirjobs or {}).items()
        ],
    )
    request = PerformanceRequest(
        schedule=schedule or unique_schedule(),
        location_id=location.id,
        ordinariumwork_id=work.id,
        artist_id=None,
        description=None,
        choirjob_defaultfee=35,
        instrument_defaultfee=60,
        voice_defaultfee=110,
        extracost_amount=extracost_amount,
        extracost_description=extracost_description,
        setup=setup,
        proprium=[],
        rehearsals=[],
    )
    performance = performance_service.create_performance(db_session, request)
    return performance.id


def get_performance(db_session: Session, performance_id: int) -> Performance:
    return db_session.execute(
        select(Performance).where(Performance.id == performance_id)
    ).scalar_one()


def move_to_past(db_session: Session, performance_id: int) -> None:
    performance = get_performance(db_session, performance_id)
    performance.schedule = local_now() - timedelta(days=1)
    db_session.commit()


_POSITION_COLUMN_NAMES = {
    "instruments": "instrument_id",
    "voices": "voice_id",
    "choirjobs": "choirjob_id",
}


def create_booking(
    db_session: Session,
    performance_id: int,
    user_id: int,
    position_type: str,
    position_id: int,
    *,
    fee: int = 80,
    order: int = 0,
) -> Booking:
    now = datetime.now(UTC)
    booking = Booking(
        performance_id=performance_id,
        user_id=user_id,
        fee=fee,
        order=order,
        created_at=now,
        updated_at=now,
        **{_POSITION_COLUMN_NAMES[position_type]: position_id},
    )
    db_session.add(booking)
    db_session.commit()
    return booking


def create_booking_request(
    db_session: Session,
    performance_id: int,
    user_id: int,
    *,
    notbooked_at: datetime | None = None,
) -> BookingRequest:
    now = datetime.now(UTC)
    request = BookingRequest(
        performance_id=performance_id,
        user_id=user_id,
        notbooked_at=notbooked_at,
        created_at=now,
        updated_at=now,
    )
    db_session.add(request)
    db_session.commit()
    return request


def create_named_user(db_session: Session, *, surname: str, givenname: str) -> User:
    user = User(
        surname=surname,
        givenname=givenname,
        email=f"{unique('user')}@example.test",
        auth_password=get_password_hash("correct-horse-battery-staple"),
    )
    db_session.add(user)
    db_session.commit()
    return user


def qualify(
    db_session: Session, user_id: int, position_type: str, position_id: int
) -> None:
    create_user_position(
        db_session,
        user_id=user_id,
        position_type=position_type,
        position_id=position_id,
    )
