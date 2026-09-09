"""convert genuinely utc timestamp columns to timestamptz

Revision ID: 0936ab290fc2
Revises: e56ce1ea52e1
Create Date: 2026-09-08 15:15:10.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0936ab290fc2"
down_revision: str | Sequence[str] | None = "e56ce1ea52e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every genuinely-UTC DateTime() column in the schema -- (table, column,
# existing_nullable). Excludes Performance.schedule/PerformanceRehearsal.
# schedule, which are naive local wall-clock values in Settings.
# app_timezone, not UTC (see app.core.datetime_utils module docstring).
# Every one of these 66 columns was already written exclusively via
# datetime.now(UTC) in Python before this migration, so an explicit
# `AT TIME ZONE 'UTC'` cast reinterprets each stored naive value as the UTC
# instant it always meant -- independent of the database session's own
# TimeZone setting (currently Etc/UTC server-wide, verified), so this stays
# correct even if that server-wide setting is ever changed later.
_TIMESTAMPTZ_COLUMNS: list[tuple[str, str, bool]] = [
    # 7 tables via the two shared mixins (CoreelementColumns/
    # RepertoireWorkColumns) -- created_at/updated_at pairs.
    ("choirjobs", "created_at", True),
    ("choirjobs", "updated_at", True),
    ("instruments", "created_at", True),
    ("instruments", "updated_at", True),
    ("locations", "created_at", True),
    ("locations", "updated_at", True),
    ("propriumelements", "created_at", True),
    ("propriumelements", "updated_at", True),
    ("voices", "created_at", True),
    ("voices", "updated_at", True),
    ("ordinariumworks", "created_at", True),
    ("ordinariumworks", "updated_at", True),
    ("propriumworks", "created_at", True),
    ("propriumworks", "updated_at", True),
    # 19 individually-declared created_at/updated_at pairs.
    ("artists", "created_at", True),
    ("artists", "updated_at", True),
    ("bookings", "created_at", True),
    ("bookings", "updated_at", True),
    ("booking_logs", "created_at", True),
    ("booking_logs", "updated_at", True),
    ("booking_requests", "created_at", True),
    ("booking_requests", "updated_at", True),
    ("fees", "created_at", True),
    ("fees", "updated_at", True),
    ("ordinariumwork_positions", "created_at", True),
    ("ordinariumwork_positions", "updated_at", True),
    ("performances", "created_at", True),
    ("performances", "updated_at", True),
    ("performance_positions", "created_at", True),
    ("performance_positions", "updated_at", True),
    ("performance_proprium", "created_at", True),
    ("performance_proprium", "updated_at", True),
    ("performance_rehearsals", "created_at", True),
    ("performance_rehearsals", "updated_at", True),
    ("personal_access_tokens", "created_at", True),
    ("personal_access_tokens", "updated_at", True),
    ("request_logs", "created_at", True),
    ("request_logs", "updated_at", True),
    ("roles", "created_at", True),
    ("roles", "updated_at", True),
    ("scores", "created_at", True),
    ("scores", "updated_at", True),
    ("sent_emails", "created_at", True),
    ("sent_emails", "updated_at", True),
    ("shorturls", "created_at", True),
    ("shorturls", "updated_at", True),
    ("users", "created_at", True),
    ("users", "updated_at", True),
    ("user_positions", "created_at", True),
    ("user_positions", "updated_at", True),
    ("user_roles", "created_at", True),
    ("user_roles", "updated_at", True),
    # 1 created_at-only table (no updated_at, structural 1:1 legacy).
    ("password_reset_tokens", "created_at", True),
    # 13 additional business-event UTC columns -- no server_default/
    # trigger, stay Python-managed via datetime.now(UTC), only the storage
    # type changes. oauth2_bindings.bound_at/lastuse_at are the only two
    # NOT NULL columns in this whole list.
    ("auth_logs", "fired_at", True),
    ("oauth2_bindings", "bound_at", False),
    ("oauth2_bindings", "lastuse_at", False),
    ("personal_access_tokens", "last_used_at", True),
    ("personal_access_tokens", "expires_at", True),
    ("users", "email_verified_at", True),
    ("users", "auth_lastlogin", True),
    ("users", "auth_lastsignal", True),
    ("users", "auth_lastlogout", True),
    ("users", "deleted_at", True),
    ("booking_logs", "notified_at", True),
    ("booking_requests", "notbooked_at", True),
    ("shorturls", "latestcall_at", True),
]

# The 27 tables whose `created_at` gets a real database-level DEFAULT
# now() (26 created_at/updated_at pairs + password_reset_tokens, which
# has created_at only) -- matches app.db.models' server_default=func.now()
# declarations exactly. `server_default=func.now()` in a SQLAlchemy model
# is Autogenerate metadata only -- it does NOT itself alter an existing
# column, so the actual `ALTER COLUMN ... SET DEFAULT` has to be issued
# here explicitly, separately from the type-cast loop above. `updated_at`
# deliberately gets no DEFAULT here -- it stays NULL until the row's
# first real UPDATE fires set_updated_at() (see the next migration).
_SERVER_DEFAULT_CREATED_AT_TABLES: list[str] = [
    "choirjobs",
    "instruments",
    "locations",
    "propriumelements",
    "voices",
    "ordinariumworks",
    "propriumworks",
    "artists",
    "bookings",
    "booking_logs",
    "booking_requests",
    "fees",
    "ordinariumwork_positions",
    "performances",
    "performance_positions",
    "performance_proprium",
    "performance_rehearsals",
    "personal_access_tokens",
    "request_logs",
    "roles",
    "scores",
    "sent_emails",
    "shorturls",
    "users",
    "user_positions",
    "user_roles",
    "password_reset_tokens",
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, nullable in _TIMESTAMPTZ_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            existing_nullable=nullable,
        )
    for table in _SERVER_DEFAULT_CREATED_AT_TABLES:
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the DEFAULT first, then reverse the type cast -- the exact
    # inverse order of upgrade(). TIMESTAMPTZ -> naive TIMESTAMP,
    # re-expressed in UTC wall-clock terms, is lossless since every value
    # in these columns is a real UTC instant either way.
    for table in reversed(_SERVER_DEFAULT_CREATED_AT_TABLES):
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            server_default=None,
            existing_nullable=True,
        )
    for table, column, nullable in reversed(_TIMESTAMPTZ_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            existing_nullable=nullable,
        )
