"""Shared primary-key column factory: every table's `id` is declared as
`id: Mapped[uuid.UUID] = uuid_pk()`, so a single place guarantees that no
table ends up with a different default.

Generation is server-side via PostgreSQL 18's native `uuidv7()` (time-ordered,
no extension required), the same "the database manages its own defaults"
convention as `created_at`/`updated_at`, not a Python-side UUID library."""

from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

if TYPE_CHECKING:
    import uuid


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=text("uuidv7()"))
