"""The created_at and updated_at columns of auth_logs and oauth2_bindings:
what the migration leaves behind, and what its upgrade does to rows that
already exist."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from app.db.models.auth_log import AuthLog
from app.db.models.oauth2_binding import Oauth2Binding
from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from app.db.models.user import User

_MIGRATION = "b8c9d0e1f2a3_add_timestamps_to_auth_logs_and_oauth2_bindings.py"
_TABLES = ["auth_logs", "oauth2_bindings"]
_EARLIER = datetime(2020, 1, 1, tzinfo=UTC)
_LATER = datetime(2021, 6, 1, tzinfo=UTC)


def _auth_log(db: Session, **overrides: object) -> AuthLog:
    fields: dict[str, object] = {"event": "Login", "fired_at": _EARLIER}
    fields.update(overrides)
    row = AuthLog(**fields)
    db.add(row)
    db.flush()
    return row


def _binding(db: Session, user: User, **overrides: object) -> Oauth2Binding:
    fields: dict[str, object] = {
        "provider": "google",
        "remote_id": uuid.uuid4().hex,
        "remote_name": "Max Muster",
        "local_id": user.id,
        "bound_at": _EARLIER,
        "lastuse_at": _LATER,
    }
    fields.update(overrides)
    row = Oauth2Binding(**fields)
    db.add(row)
    db.flush()
    return row


def _trigger_count(db: Session, table: str) -> int:
    return db.execute(
        text(
            "SELECT count(*) FROM information_schema.triggers "
            "WHERE event_object_table = :table AND trigger_name = 'set_updated_at'"
        ),
        {"table": table},
    ).scalar_one()


@pytest.mark.parametrize("table", _TABLES)
def test_the_table_has_the_trigger_and_a_required_created_at(
    db_session: Session, table: str
):
    column = db_session.execute(
        text(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = 'created_at'"
        ),
        {"table": table},
    ).one()

    assert _trigger_count(db_session, table) == 1
    assert tuple(column) == ("NO", "now()")


def test_a_new_auth_log_row_gets_created_at_and_no_updated_at(db_session: Session):
    row = _auth_log(db_session)
    db_session.expire(row)

    assert row.created_at is not None
    assert row.created_at > _EARLIER
    assert row.updated_at is None


def test_an_update_of_an_auth_log_row_sets_updated_at(db_session: Session):
    row = _auth_log(db_session)

    row.ip_address = "203.0.113.7"
    db_session.flush()
    db_session.expire(row)

    assert row.updated_at is not None


def test_a_new_binding_gets_created_at_and_an_update_sets_updated_at(
    db_session: Session, make_user: Callable[..., User]
):
    binding = _binding(db_session, make_user())
    db_session.expire(binding)
    assert binding.created_at > _EARLIER
    assert binding.updated_at is None

    binding.remote_name = "Anderer Name"
    db_session.flush()
    db_session.expire(binding)

    assert binding.updated_at is not None


def test_the_upgrade_gives_existing_rows_the_time_of_their_event(
    db_session: Session, make_user: Callable[..., User]
):
    user = make_user()
    run_migration(db_session, _MIGRATION, "downgrade")
    db_session.execute(
        text("INSERT INTO auth_logs (event, fired_at) VALUES ('Login', :fired_at)"),
        {"fired_at": _EARLIER},
    )
    db_session.execute(
        text(
            "INSERT INTO oauth2_bindings "
            "(provider, remote_id, remote_name, local_id, bound_at, lastuse_at) "
            "VALUES ('google', :remote_id, 'Max', :local_id, :bound_at, :used_at)"
        ),
        {
            "remote_id": uuid.uuid4().hex,
            "local_id": user.id,
            "bound_at": _EARLIER,
            "used_at": _LATER,
        },
    )

    run_migration(db_session, _MIGRATION)

    created = db_session.execute(
        text("SELECT created_at FROM auth_logs WHERE fired_at = :t"), {"t": _EARLIER}
    ).scalar_one()
    bound = db_session.execute(
        text("SELECT created_at FROM oauth2_bindings WHERE local_id = :id"),
        {"id": user.id},
    ).scalar_one()
    assert created == _EARLIER
    assert bound == _EARLIER


@pytest.mark.parametrize("table", _TABLES)
def test_the_downgrade_removes_columns_and_trigger(db_session: Session, table: str):
    run_migration(db_session, _MIGRATION, "downgrade")

    columns = (
        db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table "
                "AND column_name IN ('created_at', 'updated_at')"
            ),
            {"table": table},
        )
        .scalars()
        .all()
    )
    assert columns == []
    assert _trigger_count(db_session, table) == 0
