from datetime import datetime

from pydantic import BaseModel


class RequestLogUserSummaryOutput(BaseModel):
    """One row of Legacy's `Content/Administrator/RequestLogs/Index.vue`
    user list -- users who have at least one RequestLog row in the
    requested month."""

    id: int
    label: str


class RequestLogEntryOutput(BaseModel):
    """1:1 Legacy's `RequestLog\\Short` resource."""

    id: int
    created_at: datetime
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
    created_at: datetime
