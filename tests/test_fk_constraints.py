"""Tests for the FK-hardening slice (2026-09) and the polymorphy-redesign
slice that completes it (2026-09): every non-polymorphic `*_id` column
across the schema got a real `ForeignKey` with an explicit `ondelete=`
(RESTRICT/CASCADE/SET NULL, see the model docstrings for the per-column
reasoning) -- previously these were plain integers with no DB constraint
at all. The polymorphy-redesign slice closes the last gap the FK-hardening
slice deliberately left open: `position_type`/`position_id` (replaced by
`instrument_id`/`voice_id`/`choirjob_id`, see
app.db.models.position_columns_mixin.PositionColumns) and
`personal_access_tokens.tokenable_type`/`tokenable_id` (replaced by a real
`user_id` foreign key). These tests exercise the database constraint
directly (raw SQL DELETEs, bypassing the service layer's own dependency
checks entirely) to verify the constraint itself, not the service-level
guard that already existed for most of these tables. Schema comes from the
real Alembic migrations (see conftest.py's session-scoped _create_schema
fixture), same as tests/test_schema_hardening.py."""

import uuid
from collections.abc import Callable
from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.artist import Artist
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.client_user_agent import ClientUserAgent
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.ordinariumwork_position import OrdinariumworkPosition
from app.db.models.performance import Performance
from app.db.models.performance_position import PerformancePosition
from app.db.models.performance_proprium import PerformanceProprium
from app.db.models.performance_rehearsal import PerformanceRehearsal
from app.db.models.personal_access_token import PersonalAccessToken
from app.db.models.propriumelement import Propriumelement
from app.db.models.propriumwork import Propriumwork
from app.db.models.request_log import RequestLog
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_position import UserPosition
from app.db.models.user_role import UserRole
from app.db.models.voice import Voice


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_artist(db_session: Session) -> Artist:
    artist = Artist(surname=_unique("Komponist"), givenname="Given", composer=True)
    db_session.add(artist)
    db_session.flush()
    return artist


def _make_location(db_session: Session) -> Location:
    location = Location(
        name=_unique("Ort"), order=0, address="Adresse 1", color="000000"
    )
    db_session.add(location)
    db_session.flush()
    return location


def _make_ordinariumwork(db_session: Session) -> Ordinariumwork:
    artist = _make_artist(db_session)
    work = Ordinariumwork(name=_unique("Werk"), artist_id=artist.id)
    db_session.add(work)
    db_session.flush()
    return work


def _make_propriumelement(db_session: Session) -> Propriumelement:
    element = Propriumelement(name=_unique("Element"), order=0)
    db_session.add(element)
    db_session.flush()
    return element


def _make_propriumwork(db_session: Session) -> Propriumwork:
    artist = _make_artist(db_session)
    work = Propriumwork(name=_unique("Proprium"), artist_id=artist.id)
    db_session.add(work)
    db_session.flush()
    return work


def _make_instrument(db_session: Session) -> Instrument:
    instrument = Instrument(name=_unique("Instrument"), order=0)
    db_session.add(instrument)
    db_session.flush()
    return instrument


def _make_voice(db_session: Session) -> Voice:
    voice = Voice(name=_unique("Stimme"), order=0)
    db_session.add(voice)
    db_session.flush()
    return voice


def _make_performance(db_session: Session) -> Performance:
    ordinariumwork = _make_ordinariumwork(db_session)
    location = _make_location(db_session)
    performance = Performance(
        schedule=datetime(2099, 1, 1, 12, 0, 0),  # noqa: DTZ001 -- naive on purpose
        location_id=location.id,
        ordinariumwork_id=ordinariumwork.id,
    )
    db_session.add(performance)
    db_session.flush()
    return performance


class TestRestrictForeignKeys:
    """Two representative columns, not all eleven -- performances.
    location_id (a freshly-added FK on a Phase-1-legacy table) and
    user_roles.role_id (an existing FK that only got its ondelete=
    retrofitted), covering both "brand new constraint" and "ondelete=
    added to an existing one"."""

    def test_deleting_a_referenced_location_is_rejected(self, db_session: Session):
        location = _make_location(db_session)
        ordinariumwork = _make_ordinariumwork(db_session)
        db_session.add(
            Performance(
                schedule=datetime(2099, 1, 1, 12, 0, 0),  # noqa: DTZ001
                location_id=location.id,
                ordinariumwork_id=ordinariumwork.id,
            )
        )
        db_session.flush()

        # Postgres phrases a RESTRICT violation as "violates RESTRICT
        # setting of foreign key constraint" (not the plain "violates
        # foreign key constraint" a default NO ACTION FK raises) -- match
        # only the substring both forms share.
        with pytest.raises(IntegrityError, match="foreign key constraint"):
            db_session.execute(
                text("DELETE FROM locations WHERE id = :id"), {"id": location.id}
            )
        db_session.rollback()

    def test_deleting_a_role_still_assigned_to_a_user_is_rejected(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        role_name = _unique("role")
        make_user(roles=[role_name])
        role_id = db_session.execute(
            select(Role.id).where(Role.name == role_name)
        ).scalar_one()

        with pytest.raises(IntegrityError, match="foreign key constraint"):
            db_session.execute(
                text("DELETE FROM roles WHERE id = :id"), {"id": role_id}
            )
        db_session.rollback()


class TestCascadeForeignKeys:
    """Deletes go straight to the database (not through ordinariumwork_
    service.delete_ordinariumwork()/performance_service.delete_performance(),
    which no longer clean up these child tables themselves -- the CASCADE
    constraint took that job over, see those services' docstrings)."""

    def test_deleting_an_ordinariumwork_cascades_to_its_positions(
        self, db_session: Session
    ):
        ordinariumwork = _make_ordinariumwork(db_session)
        ordinariumwork_id = ordinariumwork.id
        instrument = _make_instrument(db_session)
        db_session.add(
            OrdinariumworkPosition(
                ordinariumwork_id=ordinariumwork_id,
                instrument_id=instrument.id,
                quantity=1,
            )
        )
        db_session.flush()

        db_session.execute(
            text("DELETE FROM ordinariumworks WHERE id = :id"),
            {"id": ordinariumwork_id},
        )
        # expire_on_commit would otherwise try to refresh `ordinariumwork`
        # from a row that no longer exists on the next attribute access
        # below -- the plain int captured above avoids that.
        db_session.commit()

        remaining = (
            db_session.execute(
                select(OrdinariumworkPosition).where(
                    OrdinariumworkPosition.ordinariumwork_id == ordinariumwork_id
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []

    def test_deleting_a_performance_cascades_to_positions_proprium_rehearsals(
        self, db_session: Session
    ):
        performance = _make_performance(db_session)
        performance_id = performance.id
        propriumelement = _make_propriumelement(db_session)
        propriumwork = _make_propriumwork(db_session)
        instrument = _make_instrument(db_session)
        db_session.add_all(
            [
                PerformancePosition(
                    performance_id=performance_id,
                    instrument_id=instrument.id,
                    quantity=1,
                ),
                PerformanceProprium(
                    performance_id=performance_id,
                    propriumelement_id=propriumelement.id,
                    propriumwork_id=propriumwork.id,
                ),
                PerformanceRehearsal(
                    performance_id=performance_id,
                    schedule=datetime(2099, 1, 1, 10, 0, 0),  # noqa: DTZ001
                ),
            ]
        )
        db_session.flush()

        db_session.execute(
            text("DELETE FROM performances WHERE id = :id"), {"id": performance_id}
        )
        db_session.commit()

        assert (
            db_session.execute(
                select(PerformancePosition).where(
                    PerformancePosition.performance_id == performance_id
                )
            )
            .scalars()
            .all()
            == []
        )
        assert (
            db_session.execute(
                select(PerformanceProprium).where(
                    PerformanceProprium.performance_id == performance_id
                )
            )
            .scalars()
            .all()
            == []
        )
        assert (
            db_session.execute(
                select(PerformanceRehearsal).where(
                    PerformanceRehearsal.performance_id == performance_id
                )
            )
            .scalars()
            .all()
            == []
        )

    def test_deleting_a_user_cascades_to_their_positions(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        user = make_user()
        user_id = user.id
        instrument = _make_instrument(db_session)
        db_session.add(UserPosition(user_id=user_id, instrument_id=instrument.id))
        db_session.flush()

        db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        db_session.commit()

        remaining = (
            db_session.execute(
                select(UserPosition).where(UserPosition.user_id == user_id)
            )
            .scalars()
            .all()
        )
        assert remaining == []

    def test_deleting_a_user_cascades_to_their_personal_access_tokens(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        user = make_user()
        user_id = user.id
        db_session.add(
            PersonalAccessToken(user_id=user_id, name="session", token=_unique("token"))
        )
        db_session.flush()

        db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        db_session.commit()

        remaining = (
            db_session.execute(
                select(PersonalAccessToken).where(
                    PersonalAccessToken.user_id == user_id
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []


class TestPositionForeignKeys:
    """Two representative columns, not all eleven instrument_id/voice_id/
    choirjob_id FKs across the five polymorphic tables -- Booking.
    instrument_id (RESTRICT) and UserPosition.voice_id (RESTRICT), covering
    both a three-way table and its distinct model."""

    def test_deleting_an_instrument_still_booked_is_rejected(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        performance = _make_performance(db_session)
        user = make_user()
        instrument = _make_instrument(db_session)
        db_session.add(
            PerformancePosition(
                performance_id=performance.id, instrument_id=instrument.id, quantity=1
            )
        )
        db_session.flush()
        db_session.add(
            Booking(
                performance_id=performance.id,
                user_id=user.id,
                instrument_id=instrument.id,
                order=0,
                fee=0,
            )
        )
        db_session.flush()

        with pytest.raises(IntegrityError, match="foreign key constraint"):
            db_session.execute(
                text("DELETE FROM instruments WHERE id = :id"), {"id": instrument.id}
            )
        db_session.rollback()

    def test_deleting_a_voice_still_qualifying_a_user_is_rejected(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        user = make_user()
        voice = _make_voice(db_session)
        db_session.add(UserPosition(user_id=user.id, voice_id=voice.id))
        db_session.flush()

        with pytest.raises(IntegrityError, match="foreign key constraint"):
            db_session.execute(
                text("DELETE FROM voices WHERE id = :id"), {"id": voice.id}
            )
        db_session.rollback()


class TestSetNullForeignKeys:
    def test_deleting_a_performance_nulls_out_booking_log_performance_id(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        performance = _make_performance(db_session)
        user = make_user()
        instrument = _make_instrument(db_session)
        log = BookingLog(
            performance_id=performance.id,
            user_id=user.id,
            booking_type="book",
            instrument_id=instrument.id,
            fee=0,
        )
        db_session.add(log)
        db_session.flush()

        db_session.execute(
            text("DELETE FROM performances WHERE id = :id"), {"id": performance.id}
        )
        db_session.commit()
        db_session.expire(log)

        assert log.performance_id is None
        assert log.user_id == user.id

    def test_deleting_a_user_nulls_out_booking_log_user_id(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        performance = _make_performance(db_session)
        user = make_user()
        instrument = _make_instrument(db_session)
        log = BookingLog(
            performance_id=performance.id,
            user_id=user.id,
            booking_type="book",
            instrument_id=instrument.id,
            fee=0,
        )
        db_session.add(log)
        db_session.flush()

        db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
        db_session.commit()
        db_session.expire(log)

        assert log.user_id is None
        assert log.performance_id == performance.id

    def test_deleting_a_client_user_agent_nulls_out_request_log_reference(
        self, db_session: Session
    ):
        agent = ClientUserAgent(string="pytest-agent/1.0")
        db_session.add(agent)
        db_session.flush()
        entry = RequestLog(
            client_ip="203.0.113.1",
            client_ips=[],
            client_user_agent_id=agent.id,
            user_id=None,
            request_method="GET",
            request_path=_unique("/fk-probe"),
            request_input=None,
            response_status=200,
            response_content=None,
            memory_usage=1,
        )
        db_session.add(entry)
        db_session.flush()

        db_session.execute(
            text("DELETE FROM client_user_agents WHERE id = :id"), {"id": agent.id}
        )
        db_session.commit()
        db_session.expire(entry)

        assert entry.client_user_agent_id is None


class TestUserRolesOndelete:
    def test_deleting_a_user_cascades_to_their_user_role_rows(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        user = make_user(roles=[_unique("role")])
        user_id = user.id

        db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        db_session.commit()

        remaining = (
            db_session.execute(select(UserRole).where(UserRole.user_id == user_id))
            .scalars()
            .all()
        )
        assert remaining == []
