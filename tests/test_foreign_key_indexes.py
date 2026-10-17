"""Every foreign key carries an index on its referencing column.

Without one, deleting or updating a parent row scans the whole child table
and joins from the parent side are unindexed. The schema comes from the real
Alembic migrations (see conftest.py's session-scoped _create_schema fixture),
so this checks what production gets, not only what the models declare."""

from sqlalchemy import text

from app.db.database import engine

_UNINDEXED_FOREIGN_KEYS = text(
    """
    SELECT c.conrelid::regclass::text || '.' || a.attname AS foreign_key
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    WHERE c.contype = 'f'
      AND NOT EXISTS (
          SELECT 1 FROM pg_index i
          WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1]
      )
    ORDER BY 1
    """
)


def test_every_foreign_key_has_an_index_on_its_referencing_column():
    with engine.connect() as connection:
        unindexed = connection.execute(_UNINDEXED_FOREIGN_KEYS).scalars().all()

    assert unindexed == []
