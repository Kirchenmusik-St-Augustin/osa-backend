"""The columns of the sent mails: the template key and the four columns every
mail carries."""

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.migration_helpers import run_migration

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

_MIGRATION = "a3b4c5d6e7f8_name_and_require_the_sent_email_columns.py"
_REQUIRED = ["from", "subject", "body", "template_key"]


def _insert(db: Session, **values: str | None) -> uuid.UUID:
    row = {
        "from": "no-reply@example.test",
        "subject": "Betreff",
        "body": "Text",
        "template_key": "test-mail",
    }
    row.update(values)
    columns = ", ".join(f'"{name}"' for name in row)
    placeholders = ", ".join(f":p{index}" for index in range(len(row)))
    return db.execute(
        text(
            f"INSERT INTO sent_emails ({columns}) VALUES ({placeholders}) RETURNING id"  # noqa: S608
        ),
        {f"p{index}": value for index, value in enumerate(row.values())},
    ).scalar_one()


def _columns(db: Session) -> dict[str, str]:
    return dict(
        db.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'sent_emails'"
            )
        ).all()
    )


def test_the_template_key_replaces_the_headers_column(db_session: Session):
    columns = _columns(db_session)

    assert "template_key" in columns
    assert "headers" not in columns


@pytest.mark.parametrize("column", _REQUIRED)
def test_a_mail_without_a_required_column_is_refused(db_session: Session, column: str):
    with pytest.raises(IntegrityError), db_session.begin_nested():
        _insert(db_session, **{column: None})


@pytest.mark.parametrize("column", _REQUIRED)
def test_the_required_columns_are_not_nullable(db_session: Session, column: str):
    assert _columns(db_session)[column] == "NO"


def test_the_upgrade_keeps_the_stored_values(db_session: Session):
    run_migration(db_session, _MIGRATION, "downgrade")
    mail_id = db_session.execute(
        text(
            'INSERT INTO sent_emails ("from", subject, body, headers) '
            "VALUES ('a@example.test', 'Betreff', 'Text', 'password-reset') "
            "RETURNING id"
        )
    ).scalar_one()

    run_migration(db_session, _MIGRATION)

    assert (
        db_session.execute(
            text("SELECT template_key FROM sent_emails WHERE id = :id"),
            {"id": mail_id},
        ).scalar_one()
        == "password-reset"
    )


def test_the_downgrade_restores_the_old_name_and_allows_null_again(
    db_session: Session,
):
    run_migration(db_session, _MIGRATION, "downgrade")

    columns = _columns(db_session)
    assert "headers" in columns
    assert "template_key" not in columns
    assert {columns[c] for c in ("from", "subject", "body", "headers")} == {"YES"}
