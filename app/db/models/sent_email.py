import uuid

from sqlalchemy import Computed, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk

# Only "smtp" is written today; the other transports are kept because rows
# from earlier years carry them.
sent_email_mailer_enum = Enum(
    "smtp", "log", "failover", "mailgun", name="sent_email_mailer"
)

# Counts the addresses of one list column: whitespace around the list or a
# comma is not part of an address and an empty element is not an address.
# Spelled the way PostgreSQL renders the stored expression (explicit casts),
# because Alembic compares the model's text with the reflected one when it
# checks the models against the schema; the migration that adds the column
# carries the same logic without the casts.
_RECIPIENT_COUNT_EXPRESSION = " + ".join(
    "cardinality(array_remove(regexp_split_to_array(regexp_replace("
    f"(COALESCE({column}, ''::character varying))::text, "
    "'^\\s+|\\s+$'::text, ''::text, 'g'::text), '\\s*,\\s*'::text), ''::text))"
    for column in ('"to"', "cc", "bcc")
)


class SentEmail(TimestampColumns, Base):
    """Log of every mail sent (or suppressed). `mail_from` maps to the
    actual `from` column (a reserved Python keyword) via mapped_column's
    explicit column-name argument. `template_key` is the key of the template
    the mailer rendered (e.g. "password-reset"); rows from earlier years still
    hold the raw header text of their mail there."""

    __tablename__ = "sent_emails"
    __table_args__ = (Index("sent_emails_created_at_index", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    mail_from: Mapped[str] = mapped_column("from")
    to: Mapped[str | None]
    cc: Mapped[str | None]
    bcc: Mapped[str | None]
    subject: Mapped[str]
    body: Mapped[str]
    template_key: Mapped[str]
    mailer: Mapped[str | None] = mapped_column(sent_email_mailer_enum)
    # Number of addresses in to, cc and bcc together, counted by the database,
    # so the mail kill switch can sum it instead of splitting every list in
    # Python.
    recipient_count: Mapped[int] = mapped_column(
        Computed(_RECIPIENT_COUNT_EXPRESSION, persisted=True)
    )
