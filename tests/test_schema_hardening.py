"""Tests for the ongoing DB-hardening effort (2026-09): the Quick-Wins
slice (missing indexes, money >= 0 CHECK constraints, the `order` ->
`sort_order` DB-level rename) and the enum-hardening slice
(`booking_type`/`position_type`/scores' `*art`/`inhalt`/`sparte` columns
converted from varchar+CHECK to native Postgres ENUMs). Schema comes from
the real Alembic migrations (see conftest.py's session-scoped
_create_schema fixture) -- these tests verify actual migration output,
not just model intent."""

from datetime import datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.db.database import engine
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.fee import Fee
from app.db.models.instrument import Instrument
from app.db.models.ordinariumwork_position import OrdinariumworkPosition
from app.db.models.performance import Performance
from app.db.models.role import Role
from app.db.models.score import Score


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
        performance = Performance(
            schedule=datetime(2027, 1, 2, 12, 0),  # noqa: DTZ001 -- naive on purpose
            location_id=1,
            ordinariumwork_id=1,
            extracost_amount=None,
        )
        db_session.add(performance)
        db_session.flush()  # must not raise
        assert performance.extracost_amount is None


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

    def test_invalid_booking_type_is_rejected(self, db_session: Session):
        db_session.add(
            BookingLog(
                performance_id=1,
                user_id=1,
                booking_type="bogus",
                position_type="instruments",
                position_id=1,
                fee=0,
            )
        )
        with pytest.raises(DataError, match="invalid input value for enum"):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("booking_type", ["book", "unbook"])
    def test_valid_booking_type_values_roundtrip(
        self, db_session: Session, booking_type: str
    ):
        log = BookingLog(
            performance_id=1,
            user_id=1,
            booking_type=booking_type,
            position_type="instruments",
            position_id=1,
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


class TestPositionTypeEnum:
    """position_type is a single native Postgres ENUM shared across all
    five tables that carry it. ordinariumwork_positions alone keeps its
    own narrower 2-value CHECK on top of the shared 3-value enum --
    'choirjobs' is a perfectly valid ENUM member but must still be
    rejected there."""

    def test_invalid_position_type_is_rejected(self, db_session: Session):
        db_session.add(
            Booking(
                performance_id=1,
                user_id=1,
                position_type="bogus",
                position_id=1,
                fee=0,
            )
        )
        with pytest.raises(DataError, match="invalid input value for enum"):
            db_session.flush()
        db_session.rollback()

    def test_ordinariumwork_position_still_rejects_choirjobs(self, db_session: Session):
        db_session.add(
            OrdinariumworkPosition(
                ordinariumwork_id=1,
                position_type="choirjobs",
                position_id=1,
                quantity=1,
            )
        )
        with pytest.raises(IntegrityError, match="violates check constraint"):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("position_type", ["instruments", "voices"])
    def test_ordinariumwork_position_still_accepts_its_two_allowed_values(
        self, db_session: Session, position_type: str
    ):
        db_session.add(
            OrdinariumworkPosition(
                ordinariumwork_id=1,
                position_type=position_type,
                position_id=1,
                quantity=1,
            )
        )
        db_session.flush()  # must not raise

    @pytest.mark.parametrize("position_type", ["instruments", "voices", "choirjobs"])
    def test_valid_position_type_values_roundtrip(
        self, db_session: Session, position_type: str
    ):
        booking = Booking(
            performance_id=1,
            user_id=1,
            position_type=position_type,
            position_id=1,
            fee=0,
        )
        db_session.add(booking)
        db_session.flush()
        raw_value = db_session.execute(
            text("SELECT position_type FROM bookings WHERE id = :id"),
            {"id": booking.id},
        ).scalar_one()
        assert raw_value == position_type

    @pytest.mark.parametrize(
        "table_name",
        [
            "bookings",
            "booking_logs",
            "ordinariumwork_positions",
            "performance_positions",
            "user_positions",
        ],
    )
    def test_position_type_column_uses_the_shared_enum_type(self, table_name: str):
        columns = {c["name"]: c for c in inspect(engine).get_columns(table_name)}
        column_type = columns["position_type"]["type"]
        assert isinstance(column_type, postgresql.ENUM)
        assert column_type.name == "position_type"
        assert set(column_type.enums) == {"instruments", "voices", "choirjobs"}


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
