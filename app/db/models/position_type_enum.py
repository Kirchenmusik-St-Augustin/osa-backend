"""Shared Postgres native ENUM type for `position_type`, reused verbatim
across all five tables that carry it (bookings, booking_logs,
ordinariumwork_positions, performance_positions, user_positions) -- see
alembic/versions/<rev2>_convert_position_type_to_enum.py for the matching
`CREATE TYPE position_type AS ENUM (...)`. Importing this SAME object into
every model file (rather than five separate `sa.Enum(...)` calls that
merely happen to share a `name=`) is SQLAlchemy's documented pattern for a
type shared across multiple tables in one MetaData.

Deliberately built from three bare string literals, NOT a bound Python
`enum.Enum` class (`sa.Enum(SomeEnumClass)`) -- binding a real Python Enum
class here would silently reintroduce SQLAlchemy's classic
`values_callable` footgun: by default, `sa.Enum(SomeEnum)` sends each
member's NAME (e.g. "INSTRUMENTS") to Postgres, not its `.value`
("instruments"), unless `values_callable=lambda e: [m.value for m in e]`
is also supplied -- an easy detail to omit, and the failure only shows up
as a runtime DataError on the first insert/update, not at import or
mapper-configuration time. Plain string literals sidestep the problem
entirely: `Mapped[str]` stays untouched everywhere this type is used, and
every existing string comparison (`Booking.position_type == "voices"`),
dict dispatch (`POSITION_MODELS[position_type]`), and
`Literal["instruments", "voices", "choirjobs"]` alias (see
app.services.position_types.PositionType) keeps working unchanged. Do NOT
"improve" this by introducing a Python enum class."""

import sqlalchemy as sa

position_type_enum = sa.Enum("instruments", "voices", "choirjobs", name="position_type")
