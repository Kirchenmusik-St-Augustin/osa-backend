import pytest

from app.services.sql_inspector_service import (
    TableNotFoundError,
    get_table_data,
    get_valid_tables,
)


def test_get_valid_tables_includes_known_legacy_tables(db_session):
    tables = get_valid_tables(db_session)
    assert "users" in tables
    assert tables == sorted(tables)


def test_get_table_data_reports_correct_column_metadata(db_session):
    data = get_table_data(db_session, "users", page=1, page_size=1)

    columns_by_name = {column.name: column for column in data.columns}
    assert columns_by_name["id"].primary_key is True
    assert columns_by_name["id"].nullable is False
    assert columns_by_name["email"].primary_key is False


def test_get_table_data_stringifies_values_and_keeps_null_as_none(
    db_session, make_user
):
    # phone stays NULL -- make_user() never sets it.
    user = make_user()

    data = get_table_data(db_session, "users", page=1, page_size=1000)

    row = next(r for r in data.rows if r["id"] == str(user.id))
    assert row["phone"] is None
    assert row["surname"] == "Muster"


def test_get_table_data_pagination_pages_are_disjoint_and_total_is_stable(
    db_session, make_user
):
    # Doesn't assume an empty table (the test-session SQLite file is shared
    # across test modules, see tests/conftest.py's module docstring) -- only
    # asserts pagination behaves correctly relative to whatever is there.
    for _ in range(4):
        make_user()

    first_page = get_table_data(db_session, "users", page=1, page_size=2)
    second_page = get_table_data(db_session, "users", page=2, page_size=2)

    assert first_page.total == second_page.total
    assert len(first_page.rows) == 2
    assert len(second_page.rows) == 2
    first_ids = {row["id"] for row in first_page.rows}
    second_ids = {row["id"] for row in second_page.rows}
    assert first_ids.isdisjoint(second_ids)


def test_get_table_data_raises_for_unknown_table(db_session):
    # Proves the allowlist check, not just a typo case -- a raw SQL
    # injection attempt is rejected the same way an unknown name would be.
    with pytest.raises(TableNotFoundError):
        get_table_data(db_session, "users; DROP TABLE users;--", page=1, page_size=10)
