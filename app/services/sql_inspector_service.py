from typing import TYPE_CHECKING

from sqlalchemy import inspect, text

from app.schemas.sql_inspector import TableColumnOutput, TableDataOutput

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# (table, column) pairs whose values are credentials or credential equivalents:
# password hash, remember-token, session identifier, refresh-token hash,
# reset-token hash and stored mail bodies that contain one-time links. The
# table browser shows their structure but never their values.
_MASKED_COLUMNS = frozenset(
    {
        ("users", "auth_password"),
        ("users", "auth_remember_token"),
        ("personal_access_tokens", "jti"),
        ("personal_access_tokens", "refresh_token_hash"),
        ("password_reset_tokens", "token"),
        ("sent_emails", "body"),
    }
)
_MASKED_VALUE = "__masked__"
# One page can hold 100 rows of JSONB request bodies or mail HTML: a cell
# shows its beginning only.
_MAX_CELL_LENGTH = 500


class TableNotFoundError(Exception):
    """Raised when `table_name` is not a table SQLAlchemy currently sees in
    the live schema (see get_valid_tables())."""


def get_valid_tables(db: Session) -> list[str]:
    """Sorted table names from a live schema inspection -- this list IS the
    allowlist get_table_data() below validates `table_name` against, never
    a hardcoded or cached set."""
    inspector = inspect(db.get_bind())
    return sorted(inspector.get_table_names())


def _display_value(table_name: str, column_name: str, value: object) -> str | None:
    if value is None:
        return None
    if (table_name, column_name) in _MASKED_COLUMNS:
        return _MASKED_VALUE
    text_value = str(value)
    if len(text_value) <= _MAX_CELL_LENGTH:
        return text_value
    return f"{text_value[:_MAX_CELL_LENGTH]}…"


def get_table_data(
    db: Session, table_name: str, page: int, page_size: int
) -> TableDataOutput:
    """Read-only, schema-introspection-backed table browser. `table_name`
    is checked against get_valid_tables() BEFORE it is ever interpolated
    into a SQL string -- that allowlist check is what makes the two
    f-string-built statements below safe despite not being fully
    parameterized (SQL doesn't support binding identifiers, only values).
    `page`/`page_size` are always bound as query parameters, never
    interpolated."""
    if table_name not in get_valid_tables(db):
        raise TableNotFoundError

    inspector = inspect(db.get_bind())
    key_columns: list[str] = inspector.get_pk_constraint(table_name).get(
        "constrained_columns", []
    )
    primary_key_columns = set(key_columns)
    raw_columns = inspector.get_columns(table_name)
    columns = [
        TableColumnOutput(
            name=column["name"],
            type=str(column["type"]),
            nullable=column.get("nullable", True),
            primary_key=column["name"] in primary_key_columns,
        )
        for column in raw_columns
    ]

    quoted_table_name = f'"{table_name}"'
    total = db.execute(
        text(f"SELECT COUNT(*) FROM {quoted_table_name}")  # noqa: S608
    ).scalar_one()
    # Without ORDER BY the pages of a table are not stable: rows repeat or go
    # missing between page 1 and page 2. The key columns come from the
    # catalog, not from the request.
    quote = db.get_bind().dialect.identifier_preparer.quote
    order_by = ", ".join(quote(column) for column in key_columns)
    order_clause = f"ORDER BY {order_by}" if order_by else ""
    sql = (
        f"SELECT * FROM {quoted_table_name} {order_clause} "  # noqa: S608
        "LIMIT :limit OFFSET :offset"
    )
    rows_result = db.execute(
        text(sql),
        {"limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    rows = [
        {key: _display_value(table_name, key, value) for key, value in row.items()}
        for row in rows_result
    ]

    return TableDataOutput(
        table_name=table_name,
        columns=columns,
        rows=rows,
        total=total,
        page=page,
        page_size=page_size,
    )
