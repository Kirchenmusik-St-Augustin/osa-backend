"""The vocabulary columns that are native enums: what the migration leaves
behind, and what its upgrade does to the text that was stored before."""

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError

from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from app.db.models.user import User

_MIGRATION = "c9d0e1f2a3b4_convert_vocabularies_to_enums.py"

# (table, column, enum type, the words that rows may carry)
_COLUMNS = [
    ("oauth2_bindings", "provider", "oauth2_provider", ["google"]),
    ("users", "auth_lastlogin_provider", "oauth2_provider", ["google"]),
    (
        "request_logs",
        "request_method",
        "http_method",
        [
            "GET",
            "HEAD",
            "POST",
            "PUT",
            "DELETE",
            "CONNECT",
            "OPTIONS",
            "TRACE",
            "PATCH",
        ],
    ),
    (
        "sent_emails",
        "mailer",
        "sent_email_mailer",
        ["smtp", "log", "failover", "mailgun"],
    ),
    (
        "auth_logs",
        "event",
        "auth_event",
        [
            "Login",
            "Failed",
            "Lockout",
            "Logout",
            "Verified",
            "PasswordReset",
            "Attempting",
            "Validated",
            "OtherDeviceLogout",
            "CurrentDeviceLogout",
        ],
    ),
]
_COLUMN_IDS = [f"{table}.{column}" for table, column, _, _ in _COLUMNS]
_WORDS = [(table, column, words) for table, column, _, words in _COLUMNS]
_TYPES = [(table, column, type_name) for table, column, type_name, _ in _COLUMNS]

# oauth2_bindings.local_id needs a user to point at.
pytestmark = pytest.mark.usefixtures("some_user")


def _type_of(db: Session, table: str, column: str) -> str:
    return db.execute(
        text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).scalar_one()


def _labels(db: Session, type_name: str) -> list[str]:
    return list(
        db.execute(
            text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = :name ORDER BY e.enumsortorder"
            ),
            {"name": type_name},
        ).scalars()
    )


def _set_word(db: Session, table: str, column: str, word: str | None) -> uuid.UUID:
    """Writes `word` into the column of a new row of `table` (the other
    required columns get neutral values) and returns the id of the row."""
    row_id = uuid.uuid4()
    if table == "oauth2_bindings":
        user = db.execute(text("SELECT id FROM users LIMIT 1")).scalar_one()
        db.execute(
            text(
                "INSERT INTO oauth2_bindings (id, provider, remote_id, remote_name, "
                "local_id, bound_at, lastuse_at) VALUES (:id, 'google', :remote, "
                "'Max', :user, now(), now())"
            ),
            {"id": row_id, "remote": uuid.uuid4().hex, "user": user},
        )
    elif table == "request_logs":
        db.execute(
            text(
                "INSERT INTO request_logs (id, client_ip, request_method, "
                "request_path, response_status, memory_usage) "
                "VALUES (:id, '203.0.113.7', 'GET', '/x', 200, 1)"
            ),
            {"id": row_id},
        )
    elif table == "auth_logs":
        db.execute(
            text(
                "INSERT INTO auth_logs (id, event, fired_at) "
                "VALUES (:id, 'Login', now())"
            ),
            {"id": row_id},
        )
    elif table == "sent_emails":
        db.execute(
            text(
                'INSERT INTO sent_emails (id, "from", subject, body, template_key) '
                "VALUES (:id, 'a@example.test', 'Betreff', 'Text', 'test-mail')"
            ),
            {"id": row_id},
        )
    else:
        db.execute(
            text(
                "INSERT INTO users (id, surname, givenname, auth_locked, "
                "administrator) VALUES (:id, :surname, 'Max', false, false)"
            ),
            {"id": row_id, "surname": f"Muster-{uuid.uuid4().hex[:8]}"},
        )
    db.execute(
        text(f"UPDATE {table} SET {column} = :word WHERE id = :id"),  # noqa: S608
        {"word": word, "id": row_id},
    )
    return row_id


def _stored_word(db: Session, table: str, column: str, row_id: uuid.UUID) -> str | None:
    return db.execute(
        text(f"SELECT {column}::text FROM {table} WHERE id = :id"),  # noqa: S608
        {"id": row_id},
    ).scalar_one()


@pytest.fixture
def some_user(make_user: Callable[..., User]) -> User:
    return make_user()


@pytest.mark.parametrize(("table", "column", "type_name", "words"), _COLUMNS)
def test_the_column_is_a_native_enum_with_the_expected_words(
    db_session: Session, table: str, column: str, type_name: str, words: list[str]
):
    assert _type_of(db_session, table, column) == type_name
    assert _labels(db_session, type_name) == words


@pytest.mark.parametrize(("table", "column", "words"), _WORDS, ids=_COLUMN_IDS)
def test_every_word_is_stored_and_any_other_is_refused(
    db_session: Session, table: str, column: str, words: list[str]
):
    for word in words:
        _set_word(db_session, table, column, word)

    with pytest.raises(DataError), db_session.begin_nested():
        _set_word(db_session, table, column, "carrier-pigeon")


@pytest.mark.parametrize(
    ("table", "column"),
    [("sent_emails", "mailer"), ("users", "auth_lastlogin_provider")],
)
def test_the_optional_columns_still_accept_null(
    db_session: Session, table: str, column: str
):
    row_id = _set_word(db_session, table, column, None)

    assert _stored_word(db_session, table, column, row_id) is None


@pytest.mark.parametrize(("table", "column", "type_name"), _TYPES, ids=_COLUMN_IDS)
def test_the_downgrade_turns_the_columns_back_into_text_and_drops_the_types(
    db_session: Session, table: str, column: str, type_name: str
):
    run_migration(db_session, _MIGRATION, "downgrade")

    assert _type_of(db_session, table, column) == "varchar"
    assert _labels(db_session, type_name) == []


def test_the_upgrade_keeps_the_words_that_were_stored_as_text(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")
    stored_before = {
        (table, column, word): _set_word(db_session, table, column, word)
        for table, column, word in [
            ("auth_logs", "event", "OtherDeviceLogout"),
            ("sent_emails", "mailer", "mailgun"),
            ("request_logs", "request_method", "TRACE"),
            ("users", "auth_lastlogin_provider", "google"),
            ("oauth2_bindings", "provider", "google"),
        ]
    }

    run_migration(db_session, _MIGRATION)

    for (table, column, word), row_id in stored_before.items():
        assert _stored_word(db_session, table, column, row_id) == word


def test_the_upgrade_is_refused_for_a_word_outside_the_set(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")
    _set_word(db_session, "sent_emails", "mailer", "carrier-pigeon")

    with pytest.raises(DataError):
        run_migration(db_session, _MIGRATION)
