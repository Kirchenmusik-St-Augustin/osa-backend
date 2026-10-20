import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import QueuePool

from app.db.database import engine, get_db


def test_get_db_session_enforces_foreign_keys():
    """Postgres enforces FK constraints natively and unconditionally.
    user_roles is the one table with a real ForeignKey (see
    app/db/models/user_role.py); a role_id that doesn't exist must be
    rejected, not silently inserted."""
    insert_orphan = text(
        "INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"
    )
    for session in get_db():
        with pytest.raises(IntegrityError, match="foreign key constraint"):
            session.execute(
                insert_orphan, {"user_id": uuid.uuid4(), "role_id": uuid.uuid4()}
            )
        session.rollback()
        break


def test_get_db_session_can_query_schema():
    """A plain smoke test that the schema is queryable at all -- not a
    row-count assertion: other tests populate `performances` in this same
    shared, non-rolled-back test DB (see conftest.py)."""
    for session in get_db():
        result = session.execute(text("SELECT count(*) FROM performances"))
        assert result.scalar() >= 0
        break


def test_every_connection_carries_the_server_side_limits():
    names = (
        "statement_timeout",
        "idle_in_transaction_session_timeout",
        "lock_timeout",
        "application_name",
    )
    with engine.connect() as connection:
        values = {
            name: connection.execute(text(f"SHOW {name}")).scalar_one()
            for name in names
        }

    assert values == {
        "statement_timeout": "30s",
        "idle_in_transaction_session_timeout": "1min",
        "lock_timeout": "10s",
        "application_name": "osa-backend",
    }


def test_a_statement_beyond_the_timeout_is_cancelled():
    timed_out_engine = create_engine(
        engine.url, connect_args={"options": "-c statement_timeout=200"}
    )
    try:
        with (
            timed_out_engine.connect() as connection,
            pytest.raises(OperationalError, match="statement timeout"),
        ):
            connection.execute(text("SELECT pg_sleep(5)"))
    finally:
        timed_out_engine.dispose()


def test_the_pool_is_bounded():
    pool = engine.pool

    assert isinstance(pool, QueuePool)
    assert pool.size() == 5
    assert pool.timeout() == 10
    # QueuePool has no public accessor for the overflow limit.
    assert pool._max_overflow == 5
