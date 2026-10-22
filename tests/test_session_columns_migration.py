"""The columns of the session table: named for what they hold, and what the
rename does to the sessions that exist."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import inspect, text

from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from app.db.models.user import User

_MIGRATION = "b4c5d6e7f8a9_name_the_session_columns_for_what_they_hold.py"
_TABLE = "personal_access_tokens"


def _column_names(db: Session) -> set[str]:
    return {c["name"] for c in inspect(db.connection()).get_columns(_TABLE)}


def _index_names(db: Session) -> set[str]:
    return {
        i["name"] for i in inspect(db.connection()).get_indexes(_TABLE) if i["name"]
    }


def test_the_session_columns_are_named_for_what_they_hold(db_session: Session):
    columns = _column_names(db_session)

    assert {"jti", "refresh_token_hash"} <= columns
    assert columns.isdisjoint({"token", "abilities", "name", "expires_at"})


def test_the_unique_index_follows_the_column(db_session: Session):
    indexes = _index_names(db_session)

    assert "personal_access_tokens_jti_unique" in indexes
    assert "personal_access_tokens_token_unique" not in indexes


def test_the_upgrade_keeps_the_identifier_and_the_hash_of_a_session(
    db_session: Session, make_user: Callable[..., User]
):
    user = make_user()
    run_migration(db_session, _MIGRATION, "downgrade")
    jti = uuid.uuid4().hex
    db_session.execute(
        text(
            "INSERT INTO personal_access_tokens (user_id, name, token, abilities) "
            "VALUES (:user_id, 'session', :jti, 'hash-of-the-secret')"
        ),
        {"user_id": user.id, "jti": jti},
    )

    run_migration(db_session, _MIGRATION)

    row = db_session.execute(
        text("SELECT refresh_token_hash FROM personal_access_tokens WHERE jti = :jti"),
        {"jti": jti},
    ).one()
    assert row.refresh_token_hash == "hash-of-the-secret"


def test_the_downgrade_gives_the_old_columns_back(
    db_session: Session, make_user: Callable[..., User]
):
    user = make_user()
    jti = uuid.uuid4().hex
    db_session.execute(
        text(
            "INSERT INTO personal_access_tokens (user_id, jti, refresh_token_hash) "
            "VALUES (:user_id, :jti, 'hash')"
        ),
        {"user_id": user.id, "jti": jti},
    )

    run_migration(db_session, _MIGRATION, "downgrade")

    row = db_session.execute(
        text(
            "SELECT name, abilities, expires_at FROM personal_access_tokens "
            "WHERE token = :jti"
        ),
        {"jti": jti},
    ).one()
    assert tuple(row) == ("session", "hash", None)
    assert "personal_access_tokens_token_unique" in _index_names(db_session)
    assert "jti" not in _column_names(db_session)
    assert (
        db_session.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'personal_access_tokens' AND column_name = 'name'"
            )
        ).scalar_one()
        is None
    )
