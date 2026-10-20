"""Records the SQL text of every statement the test engine executes."""

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import event

from app.db.database import engine

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Connection

_SAVEPOINT_PREFIXES = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")


@contextmanager
def recorded_statements() -> Iterator[list[str]]:
    """Yields the list that fills with statements while the block runs;
    savepoint statements issued by the test isolation are left out."""
    statements: list[str] = []

    def record(
        _conn: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if not statement.lstrip().upper().startswith(_SAVEPOINT_PREFIXES):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)
