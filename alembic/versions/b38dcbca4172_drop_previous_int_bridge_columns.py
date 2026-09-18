"""drop previous int bridge columns

Revision ID: b38dcbca4172
Revises: b70c44b3cf7b
Create Date: 2026-09-14 10:27:16.836911

"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b38dcbca4172"
down_revision: str | Sequence[str] | None = "b70c44b3cf7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase C of the UUIDv7 primary-key migration -- the delayed cleanup step
# the cutover migration deliberately left for later. `id_previous_int` (on
# every former integer-PK table) and `<column>_previous_int` (on every
# former integer foreign-key column) were kept around after the cutover
# as an inert forensic trail: a way to trace a post-migration row back to
# its pre-migration integer identity if something needed cross-checking
# shortly after the switch. They have been fully decoupled from every
# constraint, index and foreign key since the cutover, and the running
# application has never read or written any of them. Enough time has
# passed with real production traffic (logins, cancellation emails, a
# fully booked performance) going through the new UUID columns without
# incident, so this migration removes the trail for good.
_PK_TABLES: list[str] = [
    "artists",
    "auth_logs",
    "booking_logs",
    "bookings",
    "booking_requests",
    "choirjobs",
    "client_user_agents",
    "fees",
    "instruments",
    "locations",
    "oauth2_bindings",
    "ordinariumworks",
    "ordinariumwork_positions",
    "performances",
    "performance_positions",
    "performance_proprium",
    "performance_rehearsals",
    "personal_access_tokens",
    "propriumelements",
    "propriumworks",
    "request_logs",
    "roles",
    "scores",
    "sent_emails",
    "shorturls",
    "user_positions",
    "users",
    "user_roles",
    "voices",
]

# (table, foreign-key column) pairs whose previous_int shadow column is
# being dropped -- unlike the bridge migration that created these
# columns, no referenced-table information is needed here, since
# dropping a column requires no join.
_FK_COLUMNS: list[tuple[str, str]] = [
    ("booking_logs", "performance_id"),
    ("booking_logs", "user_id"),
    ("booking_logs", "instrument_id"),
    ("booking_logs", "voice_id"),
    ("booking_logs", "choirjob_id"),
    ("booking_requests", "performance_id"),
    ("booking_requests", "user_id"),
    ("bookings", "performance_id"),
    ("bookings", "user_id"),
    ("bookings", "instrument_id"),
    ("bookings", "voice_id"),
    ("bookings", "choirjob_id"),
    ("oauth2_bindings", "local_id"),
    ("ordinariumwork_positions", "ordinariumwork_id"),
    ("ordinariumwork_positions", "instrument_id"),
    ("ordinariumwork_positions", "voice_id"),
    ("ordinariumworks", "artist_id"),
    ("performance_positions", "performance_id"),
    ("performance_positions", "instrument_id"),
    ("performance_positions", "voice_id"),
    ("performance_positions", "choirjob_id"),
    ("performance_proprium", "performance_id"),
    ("performance_proprium", "propriumelement_id"),
    ("performance_proprium", "propriumwork_id"),
    ("performance_rehearsals", "performance_id"),
    ("performances", "location_id"),
    ("performances", "ordinariumwork_id"),
    ("performances", "artist_id"),
    ("personal_access_tokens", "user_id"),
    ("propriumworks", "artist_id"),
    ("request_logs", "client_user_agent_id"),
    ("request_logs", "user_id"),
    ("user_positions", "user_id"),
    ("user_positions", "instrument_id"),
    ("user_positions", "voice_id"),
    ("user_positions", "choirjob_id"),
    ("user_roles", "user_id"),
    ("user_roles", "role_id"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _FK_COLUMNS:
        op.drop_column(table, f"{column}_previous_int")

    for table in _PK_TABLES:
        op.drop_column(table, "id_previous_int")

    # Every id_previous_int sequence is OWNED BY its column (verified
    # against the live database), so Postgres already dropped each one as
    # a side effect of the op.drop_column() call above -- this loop is a
    # defensive, guaranteed-safe no-op that documents intent rather than
    # a step that does real work.
    for table in _PK_TABLES:
        op.execute(f"DROP SEQUENCE IF EXISTS {table}_id_seq")


def downgrade() -> None:
    """Deliberately irreversible -- see the migration's module docstring
    for the reasoning."""
    msg = (
        "This migration cannot be meaningfully reversed: the dropped "
        "previous_int columns held historical integer identities that no "
        "longer exist anywhere else once removed. Recreating empty "
        "columns would look like a restored forensic trail without "
        "actually being one -- restore the pre-migration backup instead "
        "if the columns are genuinely still needed."
    )
    raise RuntimeError(msg)
