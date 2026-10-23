import uuid

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class ClientUserAgent(TimestampColumns, Base):
    """A dedup table for raw User-Agent header strings, referenced by
    `request_logs.client_user_agent_id`. `string` is UNIQUE:
    request_log_service's get-or-create against this table runs on every
    HTTP request, and the constraint is what makes the IntegrityError-based
    race handling there actually correct rather than just optimistic.

    This table has no update path in practice (rows are only ever inserted,
    via get-or-create), so `updated_at` stays NULL for the lifetime of a
    row."""

    __tablename__ = "client_user_agents"
    # Mirrors request_log_service._MAX_USER_AGENT_LENGTH, so no other writer
    # can store an unbounded header.
    __table_args__ = (
        CheckConstraint(
            "char_length(string) <= 512", name="client_user_agents_string_length_check"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    string: Mapped[str] = mapped_column(unique=True)
