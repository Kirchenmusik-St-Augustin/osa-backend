"""Tests for the ongoing DB-hardening effort (2026-09): the Quick-Wins
slice (missing indexes, money >= 0 CHECK constraints, the `order` ->
`sort_order` DB-level rename), the enum-hardening slice
(`booking_type`/`position_type`/scores' `*art`/`inhalt`/`sparte` columns
converted from varchar+CHECK to native Postgres ENUMs), the
JSONB-conversion slice (request_logs' three JSON-text columns and
auth_logs.payload converted to native JSONB, sent_emails.attachments
dropped as dead), and the TIMESTAMPTZ + audit-trigger slice (every
genuinely-UTC DateTime column converted to TIMESTAMPTZ, a shared Postgres
trigger function now maintains `updated_at` on every table that has one).
Schema comes from the real Alembic migrations (see conftest.py's
session-scoped _create_schema fixture) -- these tests verify actual
migration output, not just model intent."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.db.database import engine
from app.db.models.artist import Artist
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.choirjob import Choirjob
from app.db.models.fee import Fee
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.ordinariumwork_position import OrdinariumworkPosition
from app.db.models.performance import Performance
from app.db.models.request_log import RequestLog
from app.db.models.role import Role
from app.db.models.score import Score
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.db.models.voice import Voice


def _make_ordinariumwork(db_session: Session) -> Ordinariumwork:
    """FK-hardening slice (2026-09): ordinariumwork_positions.
    ordinariumwork_id/performances.ordinariumwork_id/bookings.
    performance_id-via-Performance now require a real parent row, an
    arbitrary int id no longer round-trips."""
    artist = Artist(surname="Schema-Hardening-Artist", givenname="Given", composer=True)
    db_session.add(artist)
    db_session.flush()
    ordinariumwork = Ordinariumwork(name="Schema-Hardening-Werk", artist_id=artist.id)
    db_session.add(ordinariumwork)
    db_session.flush()
    return ordinariumwork


def _make_performance(db_session: Session) -> Performance:
    ordinariumwork = _make_ordinariumwork(db_session)
    location = Location(
        name="Schema-Hardening-Ort", order=0, address="Adresse 1", color="000000"
    )
    db_session.add(location)
    db_session.flush()
    performance = Performance(
        schedule=datetime(2099, 1, 1, 12, 0, 0),  # noqa: DTZ001 -- naive on purpose
        location_id=location.id,
        ordinariumwork_id=ordinariumwork.id,
    )
    db_session.add(performance)
    db_session.flush()
    return performance


class TestMissingIndexes:
    """Index-existence checks, not query-plan/EXPLAIN assertions -- the
    project has no existing EXPLAIN-based test pattern, and an existence
    check already catches the actual regression risk here: a future
    migration accidentally dropping or renaming one of these."""

    def test_performances_schedule_index_exists(self):
        indexes = inspect(engine).get_indexes("performances")
        matching = next(
            (i for i in indexes if i["name"] == "performances_schedule_index"), None
        )
        assert matching is not None
        assert matching["column_names"] == ["schedule"]

    def test_booking_logs_composite_index_exists(self):
        indexes = inspect(engine).get_indexes("booking_logs")
        matching = next(
            (
                i
                for i in indexes
                if i["name"] == "booking_logs_performance_id_user_id_created_at_index"
            ),
            None,
        )
        assert matching is not None
        assert matching["column_names"] == [
            "performance_id",
            "user_id",
            "created_at",
        ]

    def test_bookings_user_id_index_exists(self):
        indexes = inspect(engine).get_indexes("bookings")
        matching = next(
            (i for i in indexes if i["name"] == "bookings_user_id_index"), None
        )
        assert matching is not None
        assert matching["column_names"] == ["user_id"]


class TestMoneyCheckConstraints:
    """Two representative columns, not all seven -- one NOT NULL column
    (fees.amount) and the one NULLABLE column with the special `IS NULL OR
    >= 0` shape (performances.extracost_amount), covering both constraint
    shapes actually used across the seven candidates. Both tables need no
    dependent rows (Phase 1 has no FK constraints on either)."""

    def test_negative_fee_amount_is_rejected(self, db_session: Session):
        db_session.add(Fee(name="Quick-Wins-Negative-Fee", amount=-1))
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    def test_negative_performance_extracost_amount_is_rejected(
        self, db_session: Session
    ):
        db_session.add(
            Performance(
                schedule=datetime(2027, 1, 1, 12, 0),  # noqa: DTZ001 -- naive on purpose
                location_id=1,
                ordinariumwork_id=1,
                extracost_amount=-1,
            )
        )
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    def test_null_performance_extracost_amount_is_still_allowed(
        self, db_session: Session
    ):
        performance = _make_performance(db_session)
        assert performance.extracost_amount is None


class TestScoreCountChecks:
    """Three representative columns across the three distinct groups the
    42 new CHECK constraints span (Werk metadata, holdings-quantity
    counters, instrumentation headcounts), not all 42 -- Score has zero
    FK constraints (see Score's own docstring), so no dependent rows are
    needed for any of these."""

    def test_negative_jahr_is_rejected(self, db_session: Session):
        db_session.add(Score(jahr=-1))
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    def test_negative_holdings_count_is_rejected(self, db_session: Session):
        db_session.add(Score(part1anz=-1))
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    def test_negative_instrument_headcount_is_rejected(self, db_session: Session):
        db_session.add(Score(violine1=-1))
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    def test_null_jahr_is_still_allowed(self, db_session: Session):
        score = Score(jahr=None)
        db_session.add(score)
        db_session.flush()  # must not raise
        assert score.jahr is None


class TestOrderToSortOrderRename:
    """Confirms both sides of the alias: the DB column is physically named
    `sort_order` (checked via SQLAlchemy's inspector -- the same
    introspection tool app/services/sql_inspector_service.py already
    uses), while the ORM still reads/writes it through the unchanged
    `.order` Python attribute. Role (standalone declaration) and
    Instrument (CoreelementColumns mixin) together cover both code paths
    that declare `order`."""

    @pytest.mark.parametrize(
        "table_name",
        [
            "choirjobs",
            "instruments",
            "locations",
            "propriumelements",
            "voices",
            "bookings",
            "roles",
        ],
    )
    def test_db_column_is_named_sort_order(self, table_name: str):
        columns = {col["name"] for col in inspect(engine).get_columns(table_name)}
        assert "sort_order" in columns
        assert "order" not in columns

    def test_role_order_roundtrips_through_sort_order_column(self, db_session: Session):
        role = Role(name="quick-wins-test-role", label="Quick Wins Test", order=7)
        db_session.add(role)
        db_session.flush()

        raw_value = db_session.execute(
            text("SELECT sort_order FROM roles WHERE id = :id"), {"id": role.id}
        ).scalar_one()
        assert raw_value == 7

        db_session.expire(role)
        assert role.order == 7

    def test_instrument_order_roundtrips_through_sort_order_column(
        self, db_session: Session
    ):
        instrument = Instrument(name="quick-wins-test-instrument", order=3)
        db_session.add(instrument)
        db_session.flush()

        raw_value = db_session.execute(
            text("SELECT sort_order FROM instruments WHERE id = :id"),
            {"id": instrument.id},
        ).scalar_one()
        assert raw_value == 3

        db_session.expire(instrument)
        assert instrument.order == 3


class TestBookingTypeEnum:
    """booking_logs.booking_type is a native Postgres ENUM as of this
    slice (was varchar + CheckConstraint) -- see
    app.db.models.booking_log.booking_type_enum. Nothing narrows it
    further, so an invalid value is now rejected by Postgres itself as an
    invalid enum literal (DataError), not a CHECK violation
    (IntegrityError)."""

    def test_invalid_booking_type_is_rejected(
        self, db_session: Session, make_instrument: Callable[..., Instrument]
    ):
        instrument = make_instrument()
        db_session.add(
            BookingLog(
                performance_id=1,
                user_id=1,
                booking_type="bogus",
                instrument_id=instrument.id,
                fee=0,
            )
        )
        with pytest.raises(DataError, match="invalid input value for enum"):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("booking_type", ["book", "unbook"])
    def test_valid_booking_type_values_roundtrip(
        self,
        db_session: Session,
        make_user: Callable[..., User],
        make_instrument: Callable[..., Instrument],
        booking_type: str,
    ):
        performance = _make_performance(db_session)
        user = make_user()
        instrument = make_instrument()
        log = BookingLog(
            performance_id=performance.id,
            user_id=user.id,
            booking_type=booking_type,
            instrument_id=instrument.id,
            fee=0,
        )
        db_session.add(log)
        db_session.flush()
        raw_value = db_session.execute(
            text("SELECT booking_type FROM booking_logs WHERE id = :id"),
            {"id": log.id},
        ).scalar_one()
        assert raw_value == booking_type

    def test_booking_type_column_is_a_native_enum(self):
        columns = {c["name"]: c for c in inspect(engine).get_columns("booking_logs")}
        column_type = columns["booking_type"]["type"]
        assert isinstance(column_type, postgresql.ENUM)
        assert column_type.name == "booking_type"
        assert set(column_type.enums) == {"book", "unbook"}


class TestPositionExclusiveColumns:
    """The old position_type (native enum) + position_id (plain int, no
    FK) pair is replaced by three mutually-exclusive nullable foreign keys
    -- instrument_id/voice_id/choirjob_id, see
    app.db.models.position_columns_mixin.PositionColumns -- as of the
    polymorphy-redesign slice (2026-09), enforced by a
    `num_nonnulls(...) = 1` CHECK constraint per table.
    ordinariumwork_positions structurally excludes choirjobs (it has no
    choirjob_id column at all, unlike the other four tables' three)."""

    def test_zero_of_three_set_is_rejected(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        performance = _make_performance(db_session)
        user = make_user()
        db_session.add(Booking(performance_id=performance.id, user_id=user.id, fee=0))
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    def test_two_of_three_set_is_rejected(
        self,
        db_session: Session,
        make_user: Callable[..., User],
        make_instrument: Callable[..., Instrument],
        make_voice: Callable[..., Voice],
    ):
        performance = _make_performance(db_session)
        user = make_user()
        instrument = make_instrument()
        voice = make_voice()
        db_session.add(
            Booking(
                performance_id=performance.id,
                user_id=user.id,
                instrument_id=instrument.id,
                voice_id=voice.id,
                fee=0,
            )
        )
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("column", ["instrument_id", "voice_id", "choirjob_id"])
    def test_exactly_one_set_roundtrips(
        self,
        db_session: Session,
        make_user: Callable[..., User],
        make_instrument: Callable[..., Instrument],
        make_voice: Callable[..., Voice],
        make_choirjob: Callable[..., Choirjob],
        column: str,
    ):
        performance = _make_performance(db_session)
        user = make_user()
        make_target = {
            "instrument_id": make_instrument,
            "voice_id": make_voice,
            "choirjob_id": make_choirjob,
        }[column]
        target_id = make_target().id
        booking = Booking(
            performance_id=performance.id,
            user_id=user.id,
            fee=0,
            **{column: target_id},
        )
        db_session.add(booking)
        db_session.flush()
        raw_value = db_session.execute(
            text(f"SELECT {column} FROM bookings WHERE id = :id"),  # noqa: S608
            {"id": booking.id},
        ).scalar_one()
        assert raw_value == target_id

    @pytest.mark.parametrize("column", ["instrument_id", "voice_id", "choirjob_id"])
    def test_fk_violation_when_target_does_not_exist(
        self, db_session: Session, make_user: Callable[..., User], column: str
    ):
        performance = _make_performance(db_session)
        user = make_user()
        db_session.add(
            Booking(
                performance_id=performance.id,
                user_id=user.id,
                fee=0,
                **{column: 999_999_999},
            )
        )
        with pytest.raises(IntegrityError, match="foreign key constraint"):
            db_session.flush()
        db_session.rollback()

    def test_ordinariumwork_position_zero_of_two_set_is_rejected(
        self, db_session: Session
    ):
        ordinariumwork = _make_ordinariumwork(db_session)
        db_session.add(
            OrdinariumworkPosition(ordinariumwork_id=ordinariumwork.id, quantity=1)
        )
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("column", ["instrument_id", "voice_id"])
    def test_ordinariumwork_position_accepts_its_two_allowed_columns(
        self,
        db_session: Session,
        make_instrument: Callable[..., Instrument],
        make_voice: Callable[..., Voice],
        column: str,
    ):
        ordinariumwork = _make_ordinariumwork(db_session)
        make_target = {"instrument_id": make_instrument, "voice_id": make_voice}[column]
        target_id = make_target().id
        db_session.add(
            OrdinariumworkPosition(
                ordinariumwork_id=ordinariumwork.id,
                quantity=1,
                **{column: target_id},
            )
        )
        db_session.flush()  # must not raise

    @pytest.mark.parametrize(
        "table_name",
        [
            "bookings",
            "booking_logs",
            "performance_positions",
            "user_positions",
        ],
    )
    def test_three_way_tables_have_no_position_type_column_left(self, table_name: str):
        columns = {c["name"] for c in inspect(engine).get_columns(table_name)}
        assert "position_type" not in columns
        assert "position_id" not in columns
        assert {"instrument_id", "voice_id", "choirjob_id"} <= columns

    def test_ordinariumwork_positions_has_no_choirjob_id_column(self) -> None:
        columns = {
            c["name"] for c in inspect(engine).get_columns("ordinariumwork_positions")
        }
        assert "position_type" not in columns
        assert "position_id" not in columns
        assert "choirjob_id" not in columns
        assert {"instrument_id", "voice_id"} <= columns


class TestScoreEnums:
    """scores' inhalt/sparte/twelve *art columns are native Postgres
    ENUMs as of this slice -- three distinct types (score_inhalt,
    score_sparte, score_art), not one each; the twelve *art columns share
    one score_art type. soinstr1art..soinstr4art deliberately do NOT get
    this treatment (free-text, no prior CheckConstraint)."""

    def test_invalid_art_value_is_rejected(self, db_session: Session):
        db_session.add(Score(part1art="Bogus"))
        with pytest.raises(DataError, match="invalid input value for enum"):
            db_session.flush()
        db_session.rollback()

    def test_invalid_inhalt_value_is_rejected(self, db_session: Session):
        db_session.add(Score(inhalt="Bogus"))
        with pytest.raises(DataError, match="invalid input value for enum"):
            db_session.flush()
        db_session.rollback()

    def test_invalid_sparte_value_is_rejected(self, db_session: Session):
        db_session.add(Score(sparte="Bogus"))
        with pytest.raises(DataError, match="invalid input value for enum"):
            db_session.flush()
        db_session.rollback()

    def test_valid_values_roundtrip_and_null_still_allowed(self, db_session: Session):
        score = Score(
            inhalt="Partitur", sparte="Chor", part1art="Original", part2art=None
        )
        db_session.add(score)
        db_session.flush()  # must not raise
        db_session.expire(score)
        assert score.inhalt == "Partitur"
        assert score.sparte == "Chor"
        assert score.part1art == "Original"
        assert score.part2art is None

    @pytest.mark.parametrize(
        "column_name",
        [
            "part1art",
            "part2art",
            "klausz1art",
            "klausz2art",
            "chorpart1art",
            "chorpart2art",
            "stsoprart",
            "staltart",
            "sttenart",
            "stbassart",
            "orgelart",
            "orchart",
        ],
    )
    def test_art_column_uses_the_shared_score_art_enum(self, column_name: str):
        columns = {c["name"]: c for c in inspect(engine).get_columns("scores")}
        column_type = columns[column_name]["type"]
        assert isinstance(column_type, postgresql.ENUM)
        assert column_type.name == "score_art"
        assert set(column_type.enums) == {"Original", "Kopie", "Original/Kopie"}

    def test_soinstr_art_columns_remain_plain_text_not_enum(self):
        columns = {c["name"]: c for c in inspect(engine).get_columns("scores")}
        for column_name in (
            "soinstr1art",
            "soinstr2art",
            "soinstr3art",
            "soinstr4art",
        ):
            assert not isinstance(columns[column_name]["type"], postgresql.ENUM)


class TestRequestLogsJsonb:
    """request_logs.client_ips/request_input/response_content are native
    JSONB columns as of this slice (were varchar, holding manually
    json.dumps()-encoded text) -- see
    app.services.request_log_service.record_request/get for the
    (de)serialization this removed."""

    @pytest.mark.parametrize(
        "column_name", ["client_ips", "request_input", "response_content"]
    )
    def test_columns_are_jsonb(self, column_name: str):
        columns = {c["name"]: c for c in inspect(engine).get_columns("request_logs")}
        assert isinstance(columns[column_name]["type"], postgresql.JSONB)

    def test_nested_structures_round_trip(self, db_session: Session):
        entry = RequestLog(
            client_ip="203.0.113.1",
            client_ips=["203.0.113.1"],
            client_user_agent_id=None,
            user_id=None,
            request_method="POST",
            request_path="/schema-hardening-probe",
            request_input={"nested": {"list": [1, 2, "three"], "flag": True}},
            response_status=200,
            response_content=None,
            memory_usage=1,
            created_at=datetime(2026, 6, 10, tzinfo=UTC),
            updated_at=datetime(2026, 6, 10, tzinfo=UTC),
        )
        db_session.add(entry)
        db_session.flush()

        # psycopg2's jsonb typecaster is registered at the connection
        # level by SQLAlchemy's dialect, so even this raw text() SELECT
        # (bypassing the ORM's own JSONB type handling) comes back as a
        # real Python dict, not a string.
        raw_value = db_session.execute(
            text("SELECT request_input FROM request_logs WHERE id = :id"),
            {"id": entry.id},
        ).scalar_one()
        assert raw_value == {"nested": {"list": [1, 2, "three"], "flag": True}}


class TestAuthLogsPayloadJsonb:
    """auth_logs.payload is a native JSONB column as of this slice (was
    the generic sa.JSON() type, which Postgres renders as `json`, not
    `jsonb`)."""

    def test_column_is_jsonb(self):
        columns = {c["name"]: c for c in inspect(engine).get_columns("auth_logs")}
        assert isinstance(columns["payload"]["type"], postgresql.JSONB)


class TestSentEmailsAttachmentsDropped:
    """sent_emails.attachments was verified dead (never read or written
    anywhere in the backend or frontend) and dropped outright."""

    def test_column_no_longer_exists(self):
        columns = {c["name"] for c in inspect(engine).get_columns("sent_emails")}
        assert "attachments" not in columns


class TestTimestampsAreTimestamptz:
    """Every genuinely-UTC DateTime column is TIMESTAMPTZ as of this
    slice -- introspection only. Covers one column per structural
    category (mixin-based, individually-declared, created_at-only,
    NOT NULL business-event column) rather than all 66, matching this
    file's existing "representative, not exhaustive" style."""

    @pytest.mark.parametrize(
        ("table_name", "column_name"),
        [
            ("instruments", "created_at"),  # via CoreelementColumns mixin
            ("instruments", "updated_at"),
            ("fees", "created_at"),  # individually declared
            ("fees", "updated_at"),
            ("password_reset_tokens", "created_at"),  # created_at-only
            ("oauth2_bindings", "bound_at"),  # NOT NULL business-event column
            ("users", "deleted_at"),  # nullable business-event column
            ("user_roles", "created_at"),  # junction table, still gets it
            ("user_roles", "updated_at"),
        ],
    )
    def test_column_is_timestamptz(self, table_name: str, column_name: str):
        columns = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        column_type = columns[column_name]["type"]
        assert isinstance(column_type, postgresql.TIMESTAMP)
        assert column_type.timezone is True

    @pytest.mark.parametrize(
        ("table_name", "column_name"),
        [("performances", "schedule"), ("performance_rehearsals", "schedule")],
    )
    def test_schedule_columns_stay_naive_timestamp(
        self, table_name: str, column_name: str
    ):
        # The two deliberate exclusions -- naive local wall-clock time in
        # Settings.app_timezone, not UTC (see app.core.datetime_utils
        # module docstring).
        columns = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        column_type = columns[column_name]["type"]
        assert isinstance(column_type, postgresql.TIMESTAMP)
        assert column_type.timezone is False


class TestUpdatedAtTrigger:
    """set_updated_at() BEFORE UPDATE trigger, covering three tables from
    different structural categories: instruments (mixin-based),
    ordinariumwork_positions (individually declared), user_roles
    (junction table -- the one CLAUDE.md's literal wording would
    otherwise have excluded, see the model docstring)."""

    def test_trigger_exists_on_representative_tables(self, db_session: Session):
        for table_name in ("instruments", "ordinariumwork_positions", "user_roles"):
            rows = db_session.execute(
                text(
                    "SELECT trigger_name FROM information_schema.triggers "
                    "WHERE event_object_table = :table_name "
                    "AND trigger_name = 'set_updated_at'"
                ),
                {"table_name": table_name},
            ).all()
            assert len(rows) == 1, f"missing trigger on {table_name}"

    def test_updated_at_is_null_immediately_after_insert(self, db_session: Session):
        # server_onupdate=FetchedValue() is not a server_default -- only
        # created_at gets DEFAULT now(). updated_at deliberately stays
        # NULL until the row's first real UPDATE fires the trigger; a
        # fresh row no longer gets updated_at == created_at for free.
        instrument = Instrument(name="Trigger-Test-Fresh-Instrument", order=0)
        db_session.add(instrument)
        db_session.flush()
        db_session.expire(instrument)
        assert instrument.created_at is not None
        assert instrument.updated_at is None

    def test_bare_update_advances_updated_at(self, db_session: Session):
        old_updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        instrument = Instrument(
            name="Trigger-Test-Instrument",
            order=0,
            created_at=old_updated_at,
            updated_at=old_updated_at,
        )
        db_session.add(instrument)
        db_session.flush()

        instrument.order = 5  # never touches .updated_at in Python
        db_session.flush()
        db_session.expire(instrument)

        assert instrument.updated_at is not None
        assert instrument.updated_at > old_updated_at

    def test_ordinariumwork_position_bare_update_advances_updated_at(
        self, db_session: Session, make_instrument: Callable[..., Instrument]
    ):
        old_updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        ordinariumwork = _make_ordinariumwork(db_session)
        instrument = make_instrument()
        position = OrdinariumworkPosition(
            ordinariumwork_id=ordinariumwork.id,
            instrument_id=instrument.id,
            quantity=1,
            created_at=old_updated_at,
            updated_at=old_updated_at,
        )
        db_session.add(position)
        db_session.flush()

        position.quantity = 2  # never touches .updated_at in Python
        db_session.flush()
        db_session.expire(position)

        assert position.updated_at is not None
        assert position.updated_at > old_updated_at

    def test_user_role_bare_update_advances_updated_at(
        self, db_session: Session, make_user: Callable[..., User]
    ):
        old_updated_at = datetime(2020, 1, 1, tzinfo=UTC)
        user = make_user(roles=["disponent"])
        user_role = db_session.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        ).scalar_one()
        user_role.created_at = old_updated_at
        user_role.updated_at = old_updated_at
        db_session.flush()

        user_role.role_id = user_role.role_id  # trivial no-op UPDATE
        db_session.flush()
        db_session.expire(user_role)

        assert user_role.updated_at is not None
        assert user_role.updated_at > old_updated_at
