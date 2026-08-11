import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.human_names import label_for_name
from app.db.models.client_user_agent import ClientUserAgent
from app.db.models.request_log import RequestLog
from app.db.models.user import User
from app.schemas.request_log import (
    RequestLogEntryOutput,
    RequestLogShowOutput,
    RequestLogUserDetailOutput,
    RequestLogUserSummaryOutput,
)


class RequestLogUserNotFoundError(Exception):
    """Raised when `user_id` doesn't exist at all (soft-deleted users ARE
    found, 1:1 Legacy's `User::withTrashed()->find()` here)."""


class RequestLogNotFoundError(Exception):
    """Raised when `request_log_id` doesn't exist."""


# Legacy's `RequestLog::process()` only masks 'password'/'password_confirmation'
# in the REQUEST body. Extended here (User-confirmed 2026-08-10, see
# project_osa_migration_plan memory Schritt 9) to also cover the RESPONSE
# body and a wider set of keys -- our JWT auth returns `access_token`
# directly in login/refresh response bodies (legacy's session id never
# leaves an httponly cookie), so a 1:1 narrow mask would leak live tokens
# into an administrator-readable log table. Pure security hardening, no
# legacy business result changed (CLAUDE.md: security bugs get fixed, not
# replicated).
REDACT_KEYS = frozenset(
    {
        "password",
        "password_confirmation",
        "auth_password",
        "current_password",
        "new_password",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "authorization",
    }
)
_REDACTED_VALUE = "__removed__"


def redact(value: object) -> object:
    """Recursively masks any dict key matching REDACT_KEYS (case-insensitive),
    at any nesting depth, in both dicts and lists. Returns a new structure --
    never mutates the input."""
    if isinstance(value, dict):
        return {
            key: _REDACTED_VALUE
            if isinstance(key, str) and key.lower() in REDACT_KEYS
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


# Legacy's three RequestLog::process() exclusions: route name 'dumpdb' (no
# equivalent route exists in the new backend, N/A), path starting with the
# literal string 'web' (a legacy-only routing artifact, no equivalent path
# prefix exists here, N/A), and a `skipRequestLog` response header (kept).
# Additionally excludes the liveness check `GET /` (app/api/system.py) --
# a sensible, business-neutral addition: logging every healthcheck ping
# would flood the table with zero audit value, no legacy behavior implied
# otherwise since legacy has no equivalent unauthenticated liveness route.
_SKIP_PATHS = frozenset({"/"})


def should_skip(path: str, *, skip_header_present: bool) -> bool:
    return skip_header_present or path in _SKIP_PATHS


def _get_or_create_client_user_agent(db: Session, user_agent_string: str) -> int:
    result = db.execute(
        select(ClientUserAgent.id).where(ClientUserAgent.string == user_agent_string)
    )
    existing_id = result.scalar_one_or_none()
    if existing_id is not None:
        return existing_id
    client_user_agent = ClientUserAgent(string=user_agent_string)
    db.add(client_user_agent)
    db.flush()
    return client_user_agent.id


def record_request(
    db: Session,
    *,
    client_ip: str,
    client_ips: list[str],
    user_id: int | None,
    user_agent_string: str | None,
    request_method: str,
    request_path: str,
    request_input: object,
    response_status: int,
    response_content: object,
    memory_usage: int,
) -> None:
    """1:1 port of legacy's `RequestLog::process($request, $response)` --
    dedupes the User-Agent string via ClientUserAgent get-or-create, then
    writes one RequestLog row. Called from RequestLoggingMiddleware via
    `starlette.concurrency.run_in_threadpool()` (this function itself stays
    a plain sync function, no event-loop awareness needed here)."""
    client_user_agent_id = (
        _get_or_create_client_user_agent(db, user_agent_string)
        if user_agent_string
        else None
    )
    # created_at/updated_at are genuine UTC audit columns (like
    # sent_emails'), not naive-Vienna business timestamps -- see
    # app.core.datetime_utils module docstring for the distinction.
    now = datetime.now(UTC)
    db.add(
        RequestLog(
            client_ip=client_ip,
            client_ips=json.dumps(client_ips),
            client_user_agent_id=client_user_agent_id,
            user_id=user_id,
            request_method=request_method,
            request_path=request_path,
            request_input=json.dumps(redact(request_input)),
            response_status=response_status,
            response_content=json.dumps(redact(response_content)),
            memory_usage=memory_usage,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()


def list_users_for_month(
    db: Session, year: int, month: int
) -> list[RequestLogUserSummaryOutput]:
    """1:1 Legacy's `RequestLogController::index()` (no-user_id branch) --
    users who have at least one RequestLog row in the month, `withTrashed()`
    (no `deleted_at` filter). Sorted by (surname, givenname): Legacy's
    `User` model carries a global `OrderBySurnameGivenname` scope applied
    to EVERY User query, including this `whereIn` lookup (same lesson
    already applied in support_service.list_roles_with_contacts())."""
    month_str = f"{year:04d}-{month:02d}"
    user_ids = (
        db.execute(
            select(RequestLog.user_id)
            .where(
                func.strftime("%Y-%m", RequestLog.created_at) == month_str,
                RequestLog.user_id.is_not(None),
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    if not user_ids:
        return []
    users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    ordered = sorted(users, key=lambda user: (user.surname, user.givenname))
    # Deliberate Legacy inconsistency: unlike list_entries_for_user()'s
    # `username` below, the Index.vue pug template renders the raw
    # `{{ user.surname }} {{ user.givenname }}` fields directly (space-
    # separated, no comma) instead of the comma-format `name` accessor --
    # this page's User\Short resource never exposes a combined `name` field.
    return [
        RequestLogUserSummaryOutput(
            id=user.id,
            label=f"{user.surname} {user.givenname}"
            if user.givenname
            else user.surname,
        )
        for user in ordered
    ]


def list_entries_for_user(
    db: Session, user_id: int, year: int, month: int
) -> RequestLogUserDetailOutput:
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        raise RequestLogUserNotFoundError

    month_str = f"{year:04d}-{month:02d}"
    entries = (
        db.execute(
            select(RequestLog)
            .where(
                RequestLog.user_id == user_id,
                func.strftime("%Y-%m", RequestLog.created_at) == month_str,
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


def get(db: Session, request_log_id: int) -> RequestLogShowOutput:
    """1:1 Legacy's `RequestLog\\Show` resource. `user_name` is resolved via
    a PLAIN (non-withTrashed) User lookup -- a real, deliberate asymmetry
    vs. list_users_for_month()/list_entries_for_user() above: Legacy's
    Show resource calls bare `User::find($this->user_id)`, which returns
    null for a since-soft-deleted user (unlike the Index/IndexUser
    controllers' explicit `withTrashed()`)."""
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
        client_ips=json.loads(row.client_ips) if row.client_ips else [],
        client_user_agent_string=client_user_agent_string,
        user_id=row.user_id,
        user_name=user_name,
        request_method=row.request_method,
        request_path=row.request_path,
        request_input=json.loads(row.request_input) if row.request_input else None,
        response_status=row.response_status,
        response_content=json.loads(row.response_content)
        if row.response_content
        else None,
        memory_usage=row.memory_usage,
        created_at=row.created_at,
    )
