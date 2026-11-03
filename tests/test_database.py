import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import QueuePool

from app.db.database import engine, get_db, with_psycopg_driver


def test_get_db_session_can_query_schema():
    """The schema is queryable through get_db()."""
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


def test_the_engine_connects_through_psycopg_3():
    """The test environment names a plain postgresql:// URL, so this proves
    the driver comes from the normalisation and not from the URL."""
    assert engine.dialect.driver == "psycopg"
    assert engine.url.drivername == "postgresql+psycopg"


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (
            "postgresql://osa_app:p%40ss%2Fword@127.0.0.1:5432/osa?sslmode=disable",
            (
                "postgresql+psycopg://osa_app:p%40ss%2Fword@127.0.0.1:5432/osa"
                "?sslmode=disable"
            ),
        ),
        ("postgresql:///osa", "postgresql+psycopg:///osa"),
    ],
)
def test_a_plain_postgresql_url_gets_the_psycopg_driver(
    database_url: str, expected: str
):
    assert with_psycopg_driver(database_url) == expected


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://u:p@db.example/osa",
        "postgresql+asyncpg://u:p@db.example/osa",
        "mysql://u:p@db.example/osa",
    ],
)
def test_a_url_that_names_a_driver_or_another_database_is_left_alone(
    database_url: str,
):
    assert with_psycopg_driver(database_url) == database_url
