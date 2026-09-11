"""Shared primary-key column factory for the UUIDv7 migration -- every
one of this schema's ~29 integer-PK tables gets converted to this exact
same declaration (`id: Mapped[uuid.UUID] = uuid_pk()`), so a single
factory function is what guarantees none of them ends up with a
different default by a transcription slip.

Generation is server-side, via Postgres 18's native `uuidv7()` (no
extension required) -- the same "database manages its own defaults"
convention already used for `created_at`/`updated_at` (see
app.db.models.coreelement_mixin), not a Python-side UUID library."""

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=text("uuidv7()"))
