from typing import TYPE_CHECKING, cast, overload

from sqlalchemy import Date, func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.datetime_utils import local_day_bounds_utc, local_month_bounds_utc
from app.core.human_names import label_for_name
from app.db.models.client_user_agent import ClientUserAgent
from app.db.models.request_log import RequestLog
from app.db.models.user import User
from app.schemas.request_log import (
    RequestLogDayGroupOutput,
    RequestLogEntryOutput,
    RequestLogShowOutput,
    RequestLogUserDetailOutput,
    RequestLogUserSummaryOutput,
)

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from sqlalchemy.orm import Session

    from app.core.json_types import JsonObject, JsonValue


class RequestLogUserNotFoundError(Exception):
    """Raised when `user_id` doesn't exist at all (soft-deleted users ARE
    found)."""


class RequestLogNotFoundError(Exception):
    """Raised when `request_log_id` doesn't exist."""


# Sensitive keys are masked in both the REQUEST and the RESPONSE body --
# our JWT auth returns `access_token` directly in login/refresh response
# bodies, so without redaction live tokens would leak into an
# administrator-readable log table.
REDACT_KEYS = frozenset(
    {
        "password",
        "password_confirmation",
        "auth_password",
        "current_password",
        "new_password",
        "newpw",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "authorization",
        # Google ID token of /auth/google/callback and /auth/google/link: valid
        # for about an hour and accepted by the backend as proof of identity.
        "credential",
        "id_token",
        "client_secret",
        "refresh_secret",
    }
)
# The server accepts far longer headers; the stored string only has to tell
# clients apart for monitoring.
_MAX_USER_AGENT_LENGTH = 512
_REDACTED_VALUE = "__removed__"


@overload
def redact(value: JsonObject) -> JsonObject: ...
@overload
def redact(value: JsonValue) -> JsonValue: ...
def redact(value: JsonValue) -> JsonValue:
    """Recursively masks any dict key matching REDACT_KEYS (case-insensitive),
    at any nesting depth, in both dicts and lists. Returns a new structure --
    never mutates the input."""
    if isinstance(value, dict):
        return {
            key: _REDACTED_VALUE if key.lower() in REDACT_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


# Requests excluded from logging: those whose response carries the skip
# header, and the liveness check `GET /` (app/api/system.py) -- logging
# every healthcheck ping would flood the table with zero audit value.
_SKIP_PATHS = frozenset({"/"})


def should_skip(path: str, *, skip_header_present: bool) -> bool:
    return skip_header_present or path in _SKIP_PATHS


def _get_or_create_client_user_agent(db: Session, raw_user_agent: str) -> uuid.UUID:
    user_agent_string = raw_user_agent[:_MAX_USER_AGENT_LENGTH]
    result = db.execute(
        select(ClientUserAgent.id).where(ClientUserAgent.string == user_agent_string)
    )
    existing_id = result.scalar_one_or_none()
    if existing_id is not None:
        return existing_id
    try:
        with db.begin_nested():
            client_user_agent = ClientUserAgent(string=user_agent_string)
            db.add(client_user_agent)
            db.flush()
    except IntegrityError:
        # Lost a TOCTOU race: this table's get-or-create runs on every
        # HTTP request, so a concurrent request can insert the same new
        # user_agent_string between the SELECT above and this INSERT.
        # begin_nested()'s SAVEPOINT already rolled back the failed
        # insert -- the other request's row is committed by now, so a
        # plain re-SELECT finds it.
        return db.execute(
            select(ClientUserAgent.id).where(
                ClientUserAgent.string == user_agent_string
            )
        ).scalar_one()
    return client_user_agent.id


def record_request(
    db: Session,
    *,
    client_ip: str,
    client_ips: list[str],
    user_id: uuid.UUID | None,
    user_agent_string: str | None,
    request_method: str,
    request_path: str,
    request_input: JsonObject,
    response_status: int,
    response_content: JsonValue,
    memory_usage: int,
) -> None:
    """Dedupes the User-Agent string via ClientUserAgent get-or-create, then
    writes one RequestLog row. Called from RequestLoggingMiddleware via
    `starlette.concurrency.run_in_threadpool()` (this function itself stays
    a plain sync function, no event-loop awareness needed here)."""
    client_user_agent_id = (
        _get_or_create_client_user_agent(db, user_agent_string)
        if user_agent_string
        else None
    )
    db.add(
        RequestLog(
            client_ip=client_ip,
            client_ips=client_ips,
            client_user_agent_id=client_user_agent_id,
            user_id=user_id,
            request_method=request_method,
            request_path=request_path,
            request_input=redact(request_input),
            response_status=response_status,
            response_content=redact(response_content),
            memory_usage=memory_usage,
        )
    )
    db.commit()


def _label_without_comma(user: User) -> str:
    # Space-separated label (no comma), deliberately unlike the comma-format
    # `username` in list_entries_for_user_day() below.
    return f"{user.surname} {user.givenname}" if user.givenname else user.surname


def list_days_with_users_for_month(
    db: Session, year: int, month: int
) -> list[RequestLogDayGroupOutput]:
    """Groups the month's activity by local (Settings.app_timezone)
    calendar day, newest day first, for monitoring ("which days had
    activity, who was active"). Users per day include soft-deleted ones (no
    `deleted_at` filter), sorted by
    (surname, givenname) -- same lesson as
    support_service.list_roles_with_contacts().

    N+1-safe in exactly 2 queries regardless of day/user count, same
    batch-load-then-assemble-in-Python shape as
    performance_service._build_proprium_by_performance()."""
    month_start_utc, month_end_utc = local_month_bounds_utc(year, month)

    # Query 1/2: one row per (local day, user), grouped by the database --
    # the month holds thousands of request rows, the answer a few hundred.
    local_day = func.date(
        func.timezone(get_settings().app_timezone, RequestLog.created_at),
        type_=Date,
    )
    rows = db.execute(
        select(local_day, RequestLog.user_id)
        .where(
            RequestLog.created_at >= month_start_utc,
            RequestLog.created_at < month_end_utc,
            RequestLog.user_id.is_not(None),
        )
        .distinct()
    ).all()
    if not rows:
        return []

    user_ids_by_day: dict[date, set[uuid.UUID]] = {}
    for day, raw_user_id in rows:
        # Narrows the ORM column's nullable static type -- not a defensive
        # runtime branch: the WHERE clause above guarantees a non-null user_id.
        user_ids_by_day.setdefault(day, set()).add(cast("uuid.UUID", raw_user_id))

    all_user_ids = {uid for ids in user_ids_by_day.values() for uid in ids}
    # Query 2/2: includes soft-deleted users (no `deleted_at` filter).
    users_by_id = {
        user.id: user
        for user in db.execute(select(User).where(User.id.in_(all_user_ids)))
        .scalars()
        .all()
    }

    return [
        RequestLogDayGroupOutput(
            day=day,
            users=[
                RequestLogUserSummaryOutput(
                    id=user.id, label=_label_without_comma(user)
                )
                for user in sorted(
                    (
                        users_by_id[uid]
                        for uid in user_ids_by_day[day]
                        if uid in users_by_id
                    ),
                    key=lambda user: (user.surname, user.givenname),
                )
            ],
        )
        for day in sorted(user_ids_by_day, reverse=True)
    ]


def list_entries_for_user_day(
    db: Session, user_id: uuid.UUID, day: date
) -> RequestLogUserDetailOutput:
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        raise RequestLogUserNotFoundError

    start_utc, end_utc = local_day_bounds_utc(day)
    entries = (
        db.execute(
            select(RequestLog)
            .where(
                RequestLog.user_id == user_id,
                RequestLog.created_at >= start_utc,
                RequestLog.created_at < end_utc,
            )
            .order_by(RequestLog.created_at)
        )
        .scalars()
        .all()
    )
    return RequestLogUserDetailOutput(
        username=label_for_name(user.surname, user.givenname),
        entries=[
            RequestLogEntryOutput(
                id=entry.id,
                created_at=entry.created_at,
                request_method=entry.request_method,
                request_path=entry.request_path,
            )
            for entry in entries
            if entry.created_at is not None
        ],
    )


def get(db: Session, request_log_id: uuid.UUID) -> RequestLogShowOutput:
    """`user_name` is resolved via a plain lookup that excludes soft-deleted
    users -- a deliberate asymmetry vs. list_days_with_users_for_month()/
    list_entries_for_user_day() above, which include them: a since-soft-
    deleted user yields no `user_name` here."""
    row = db.execute(
        select(RequestLog).where(RequestLog.id == request_log_id)
    ).scalar_one_or_none()
    if row is None or row.created_at is None:
        raise RequestLogNotFoundError

    client_user_agent_string: str | None = None
    if row.client_user_agent_id is not None:
        agent = db.execute(
            select(ClientUserAgent).where(
                ClientUserAgent.id == row.client_user_agent_id
            )
        ).scalar_one_or_none()
        client_user_agent_string = agent.string if agent is not None else None

    user_name: str | None = None
    if row.user_id is not None:
        user = db.execute(
            select(User).where(User.id == row.user_id, User.deleted_at.is_(None))
        ).scalar_one_or_none()
        if user is not None:
            user_name = label_for_name(user.surname, user.givenname)

    return RequestLogShowOutput(
        id=row.id,
        client_ip=row.client_ip,
        client_ips=row.client_ips or [],
        client_user_agent_string=client_user_agent_string,
        user_id=row.user_id,
        user_name=user_name,
        request_method=row.request_method,
        request_path=row.request_path,
        request_input=row.request_input,
        response_status=row.response_status,
        response_content=row.response_content,
        memory_usage=row.memory_usage,
        created_at=row.created_at,
    )
