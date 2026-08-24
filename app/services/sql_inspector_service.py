from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.schemas.sql_inspector import TableColumnOutput, TableDataOutput


class TableNotFoundError(Exception):
    """Raised when `table_name` is not a table SQLAlchemy currently sees in
    the live schema (see get_valid_tables())."""


def get_valid_tables(db: Session) -> list[str]:
    """Sorted table names from a live schema inspection -- this list IS the
    allowlist get_table_data() below validates `table_name` against, never
    a hardcoded or cached set."""
    inspector = inspect(db.get_bind())
    return sorted(inspector.get_table_names())


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
    primary_key_columns = set(
        inspector.get_pk_constraint(table_name).get("constrained_columns", [])
    )
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
    sql = f"SELECT * FROM {quoted_table_name} LIMIT :limit OFFSET :offset"  # noqa: S608
    rows_result = db.execute(
        text(sql),
        {"limit": page_size, "offset": (page - 1) * page_size},
    ).mappings()
    rows = [
        {key: str(value) if value is not None else None for key, value in row.items()}
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
