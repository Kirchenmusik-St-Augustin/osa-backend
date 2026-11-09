import pytest
from sqlalchemy import text

from app.services.sql_inspector_service import (
    TableNotFoundError,
    get_table_data,
    get_valid_tables,
)
from tests.sql_capture import recorded_statements


def test_get_valid_tables_includes_known_tables(db_session):
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
    # Doesn't assume an empty table (the test-session database is shared
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


def test_get_table_data_orders_consecutive_pages_by_the_primary_key(
    db_session, make_user
):
    for _ in range(5):
        make_user()

    pages = [
        get_table_data(db_session, "users", page=number, page_size=2).rows
        for number in (1, 2, 3)
    ]

    ids = [row["id"] for page in pages for row in page]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


def test_get_table_data_sends_an_order_by_on_the_primary_key(db_session):
    with recorded_statements() as statements:
        get_table_data(db_session, "users", page=1, page_size=5)

    page_query = next(s for s in statements if s.startswith("SELECT * FROM"))
    assert "ORDER BY id LIMIT" in page_query


def test_get_table_data_orders_by_the_columns_of_a_composite_key_in_key_order(
    db_session,
):
    db_session.execute(
        text("CREATE TABLE inspector_composite (a int, b int, PRIMARY KEY (b, a))")
    )
    db_session.execute(
        text("INSERT INTO inspector_composite VALUES (1, 2), (2, 1), (1, 1)")
    )

    with recorded_statements() as statements:
        data = get_table_data(db_session, "inspector_composite", page=1, page_size=10)

    page_query = next(s for s in statements if s.startswith("SELECT * FROM"))
    assert "ORDER BY b, a LIMIT" in page_query
    assert [(row["b"], row["a"]) for row in data.rows] == [
        ("1", "1"),
        ("1", "2"),
        ("2", "1"),
    ]


def test_get_table_data_quotes_a_key_column_that_is_a_reserved_word(db_session):
    db_session.execute(
        text('CREATE TABLE inspector_reserved ("order" int PRIMARY KEY)')
    )
    db_session.execute(text("INSERT INTO inspector_reserved VALUES (2), (1)"))

    with recorded_statements() as statements:
        data = get_table_data(db_session, "inspector_reserved", page=1, page_size=10)

    page_query = next(s for s in statements if s.startswith("SELECT * FROM"))
    assert 'ORDER BY "order" LIMIT' in page_query
    assert [row["order"] for row in data.rows] == ["1", "2"]


def test_get_table_data_reads_a_table_without_a_primary_key_unordered(db_session):
    db_session.execute(text("CREATE TABLE inspector_no_key (value text)"))
    db_session.execute(text("INSERT INTO inspector_no_key VALUES ('a'), ('b')"))

    with recorded_statements() as statements:
        data = get_table_data(db_session, "inspector_no_key", page=1, page_size=10)

    assert sorted(row["value"] for row in data.rows) == ["a", "b"]
    page_query = next(s for s in statements if s.startswith("SELECT * FROM"))
    assert "ORDER BY" not in page_query


@pytest.mark.parametrize(("length", "shown"), [(5000, 501), (501, 501), (500, 500)])
def test_get_table_data_cuts_a_long_cell(db_session, make_user, length, shown):
    user = make_user()
    db_session.execute(
        text("UPDATE users SET surname = :value WHERE id = :id"),
        {"value": "x" * length, "id": user.id},
    )

    data = get_table_data(db_session, "users", page=1, page_size=1000)

    row = next(r for r in data.rows if r["id"] == str(user.id))
    assert len(row["surname"]) == shown
    assert row["surname"].endswith("…") == (length > 500)
