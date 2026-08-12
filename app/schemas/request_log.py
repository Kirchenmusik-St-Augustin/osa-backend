from datetime import date

from pydantic import BaseModel

from app.core.datetime_utils import UtcDatetime


class RequestLogUserSummaryOutput(BaseModel):
    """One user row nested under RequestLogDayGroupOutput.users below --
    users who were active on that day."""

    id: int
    label: str


class RequestLogDayGroupOutput(BaseModel):
    """One row of the Index endpoint's response -- a local
    (Settings.app_timezone) calendar day within the requested month that
    had at least one RequestLog entry, with the users active on that day.
    No Legacy equivalent -- Legacy's Content/Administrator/RequestLogs/
    Index.vue only ever returns a flat month-scoped user list; day grouping
    is a real functional change for post-cutover monitoring (User decision
    2026-08-12), not a 1:1 migration slice."""

    day: date
    users: list[RequestLogUserSummaryOutput]


class RequestLogEntryOutput(BaseModel):
    """1:1 Legacy's `RequestLog\\Short` resource."""

    id: int
    created_at: UtcDatetime
    request_method: str
    request_path: str


class RequestLogUserDetailOutput(BaseModel):
    """Backs `Content/Administrator/RequestLogs/IndexUser.vue` -- entries
    sorted `created_at ASC` (1:1 Legacy's own `orderBy('created_at')`)."""

    username: str
    entries: list[RequestLogEntryOutput]


class RequestLogShowOutput(BaseModel):
    """1:1 Legacy's `RequestLog\\Show` resource."""

    id: int
    client_ip: str
    client_ips: list[str]
    client_user_agent_string: str | None
    user_id: int | None
    user_name: str | None
    request_method: str
    request_path: str
    request_input: object
    response_status: int
    response_content: object
    memory_usage: int
    created_at: UtcDatetime
