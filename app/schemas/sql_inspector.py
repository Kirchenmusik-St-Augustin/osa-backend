from pydantic import BaseModel


class TableColumnOutput(BaseModel):
    """One column's metadata, as reported by SQLAlchemy's `inspect()` for
    the currently selected table."""

    name: str
    type: str
    nullable: bool
    primary_key: bool


class TableDataOutput(BaseModel):
    """One page of a table's rows plus its column metadata. `rows` values
    are always stringified (or `None`) -- this endpoint is generic across
    every table in the schema, so it deliberately doesn't attempt to
    preserve each column's native Python type."""

    table_name: str
    columns: list[TableColumnOutput]
    rows: list[dict[str, str | None]]
    total: int
    page: int
    page_size: int
