from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampColumns:
    """Creation and last-change time of a row, both TIMESTAMPTZ: `created_at`
    is populated by the database's own DEFAULT now(), `updated_at` by the
    shared set_updated_at() BEFORE UPDATE trigger registered on every table.
    Neither is ever assigned from Python."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
