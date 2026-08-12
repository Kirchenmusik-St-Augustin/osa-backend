from pydantic import BaseModel, Field

from app.core.datetime_utils import UtcDatetime


class SentEmailShortOutput(BaseModel):
    """1:1 Legacy's `SentEmail\\Short` resource -- `datetime` maps to
    `updated_at` here (NOT `created_at`, see SentEmailShowOutput below),
    matching `SentEmail::ofMonth()`'s own filter/sort column."""

    id: int
    datetime: UtcDatetime
    to: str | None
    subject: str | None


class SentEmailShowOutput(BaseModel):
    """1:1 Legacy's `SentEmail\\Show` resource -- `datetime` maps to
    `created_at` here, unlike the Short/list resource above (verified
    against Legacy source, not a typo)."""

    id: int
    mailer: str | None
    datetime: UtcDatetime
    from_: str | None = Field(alias="from")
    to: str | None
    cc: str | None
    bcc: str | None
    subject: str | None
    body: str | None
