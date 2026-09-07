"""Tests for the Quick-Wins DB-hardening slice (2026-09): missing indexes,
money >= 0 CHECK constraints, and the `order` -> `sort_order` DB-level
rename. Schema comes from the real Alembic migrations (see conftest.py's
session-scoped _create_schema fixture) -- these tests verify actual
migration output, not just model intent."""

from datetime import datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import engine
from app.db.models.fee import Fee
from app.db.models.instrument import Instrument
from app.db.models.performance import Performance
from app.db.models.role import Role


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
