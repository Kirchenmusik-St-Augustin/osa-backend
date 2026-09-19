import uuid

from pydantic import BaseModel, Field

from app.core.datetime_utils import UtcDatetime


class SentEmailShortOutput(BaseModel):
    """One row of the monthly sent-mail list -- `datetime` is the row's
    `created_at`."""

    id: uuid.UUID
    datetime: UtcDatetime
    to: str | None
    subject: str | None


class SentEmailShowOutput(BaseModel):
    """Full detail of one sent mail -- `datetime` is the row's
    `created_at`."""

    id: uuid.UUID
    mailer: str | None
    datetime: UtcDatetime
    from_: str | None = Field(alias="from")
    to: str | None
    cc: str | None
    bcc: str | None
    subject: str | None
    body: str | None
