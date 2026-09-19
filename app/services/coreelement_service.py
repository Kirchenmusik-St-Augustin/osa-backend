from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import func, select

from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork_position import OrdinariumworkPosition
from app.db.models.performance import Performance
from app.db.models.performance_position import PerformancePosition
from app.db.models.performance_proprium import PerformanceProprium
from app.db.models.propriumelement import Propriumelement
from app.db.models.role import Role
from app.db.models.user_role import UserRole
from app.db.models.voice import Voice
from app.schemas.coreelement import CoreelementRequest, CoreelementType
from app.services.errors import (
    DomainValidationError,
    FieldError,
    GeneralValidationError,
    NotFoundError,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import InstrumentedAttribute, Session

    from app.services.position_types import PositionType

CoreelementModel = Instrument | Voice | Choirjob | Location | Propriumelement | Role

# Which of PerformancePosition's three FK columns / OrdinariumworkPosition's
# two FK columns corresponds to a given position_type -- OrdinariumworkPosition
# structurally has no choirjob_id column at all (see its own model docstring),
# so it is a 2-entry table, not 3.
_PERFORMANCE_POSITION_COLUMNS: dict[
    PositionType, InstrumentedAttribute[uuid.UUID | None]
] = {
    "instruments": PerformancePosition.instrument_id,
    "voices": PerformancePosition.voice_id,
    "choirjobs": PerformancePosition.choirjob_id,
}
_ORDINARIUMWORK_POSITION_COLUMNS: dict[
    Literal["instruments", "voices"], InstrumentedAttribute[uuid.UUID | None]
] = {
    "instruments": OrdinariumworkPosition.instrument_id,
    "voices": OrdinariumworkPosition.voice_id,
}
# The subset of CoreelementModel that actually has an `active` column --
# narrows config.model back down wherever has_active_field guards the
# access at runtime (Location/Propriumelement/Role don't have this
# attribute, so a plain access would fail pyright strict).
_ActiveCoreelementModel = Instrument | Voice | Choirjob


_IN_USE_DETAIL = "Das Element kann nicht gelöscht werden, da es noch in Verwendung ist."


class CoreelementNotFoundError(NotFoundError):
    """Raised when `element_id` doesn't exist for the given CoreelementType."""


class CoreelementValidationError(DomainValidationError):
    """Field-level validation failures, one (field, message) pair per
    failing field -- same pattern as auth_service.RegistrationConflictError."""


class CoreelementInUseError(GeneralValidationError):
    """Raised when delete is blocked by a dependent row."""

    def __init__(self) -> None:
        super().__init__(_IN_USE_DETAIL)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    min_length: int
    max_length: int
    unique: bool = False


@dataclass(frozen=True)
class CoreelementTypeConfig:
    model: type[CoreelementModel]
    name_max_length: int = 60
    extra_fields: tuple[FieldSpec, ...] = ()
    has_dependencies: Callable[[Session, CoreelementModel], bool] | None = None
    # `active` isn't a validated string field like the FieldSpec-driven
    # ones above (no length bounds, no uniqueness) -- it's a plain bool
    # toggle with its own default-on-create/preserve-on-omit semantics
    # (see create_coreelement/update_coreelement below), so it gets its
    # own config flag instead of a FieldSpec entry.
    has_active_field: bool = False


def _role_has_dependent_users(db: Session, role: CoreelementModel) -> bool:
    """A Role is in use while any `user_roles` row references it."""
    count = db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
    ).scalar_one()
    return count > 0


def _make_position_dependency_check(
    position_type: PositionType,
) -> Callable[[Session, CoreelementModel], bool]:
    """Instrument/Voice/Choirjob can be referenced by an Ordinariumwork's
    Positions setup (choirjobs never actually match here,
    OrdinariumworkPosition has no choirjob_id column at all, so that check
    is skipped entirely for position_type='choirjobs' rather than issuing a
    query that could only ever return zero) AND/OR a Performance's
    Positions setup (all three types). `user_positions` references are not
    checked here -- their RESTRICT foreign keys reject such a delete at the
    database level."""

    def _check(db: Session, item: CoreelementModel) -> bool:
        ordinariumwork_count = 0
        if position_type != "choirjobs":
            ordinariumwork_count = db.execute(
                select(func.count())
                .select_from(OrdinariumworkPosition)
                .where(_ORDINARIUMWORK_POSITION_COLUMNS[position_type] == item.id)
            ).scalar_one()
        performance_count = db.execute(
            select(func.count())
            .select_from(PerformancePosition)
            .where(_PERFORMANCE_POSITION_COLUMNS[position_type] == item.id)
        ).scalar_one()
        return ordinariumwork_count > 0 or performance_count > 0

    return _check


def _location_has_dependent_performances(
    db: Session, location: CoreelementModel
) -> bool:
    count = db.execute(
        select(func.count())
        .select_from(Performance)
        .where(Performance.location_id == location.id)
    ).scalar_one()
    return count > 0


def _propriumelement_has_dependent_performances(
    db: Session, element: CoreelementModel
) -> bool:
    count = db.execute(
        select(func.count())
        .select_from(PerformanceProprium)
        .where(PerformanceProprium.propriumelement_id == element.id)
    ).scalar_one()
    return count > 0


COREELEMENT_CONFIG: dict[CoreelementType, CoreelementTypeConfig] = {
    CoreelementType.instrument: CoreelementTypeConfig(
        model=Instrument,
        has_dependencies=_make_position_dependency_check("instruments"),
        has_active_field=True,
    ),
    CoreelementType.voice: CoreelementTypeConfig(
        model=Voice,
        has_dependencies=_make_position_dependency_check("voices"),
        has_active_field=True,
    ),
    CoreelementType.choirjob: CoreelementTypeConfig(
        model=Choirjob,
        has_dependencies=_make_position_dependency_check("choirjobs"),
        has_active_field=True,
    ),
    CoreelementType.propriumelement: CoreelementTypeConfig(
        model=Propriumelement,
        has_dependencies=_propriumelement_has_dependent_performances,
    ),
    CoreelementType.location: CoreelementTypeConfig(
        model=Location,
        extra_fields=(
            FieldSpec("address", min_length=3, max_length=60),
            FieldSpec("color", min_length=3, max_length=6),
        ),
        has_dependencies=_location_has_dependent_performances,
    ),
    CoreelementType.role: CoreelementTypeConfig(
        model=Role,
        name_max_length=16,
        extra_fields=(
            FieldSpec("label", min_length=3, max_length=32, unique=True),
            FieldSpec("description", min_length=3, max_length=250),
        ),
        has_dependencies=_role_has_dependent_users,
    ),
}


def _value_taken(
    db: Session,
    model: type[CoreelementModel],
    field_name: str,
    value: str,
    exclude_id: uuid.UUID | None,
) -> bool:
    column = getattr(model, field_name)
    stmt = select(model.id).where(column == value)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _validate_name(
    db: Session, config: CoreelementTypeConfig, name: str, exclude_id: uuid.UUID | None
) -> FieldError | None:
    if not 3 <= len(name) <= config.name_max_length:
        return FieldError(
            "name",
            f"Muss zwischen 3 und {config.name_max_length} Zeichen lang sein.",
        )
    if _value_taken(db, config.model, "name", name, exclude_id):
        return FieldError("name", "Der Name ist bereits vergeben.")
    return None


def _validate_extra_field(
    db: Session,
    config: CoreelementTypeConfig,
    spec: FieldSpec,
    value: str | None,
    exclude_id: uuid.UUID | None,
) -> FieldError | None:
    if value is None:
        return FieldError(spec.name, "Dieses Feld ist erforderlich.")
    if not spec.min_length <= len(value) <= spec.max_length:
        return FieldError(
            spec.name,
            f"Muss zwischen {spec.min_length} und {spec.max_length} Zeichen lang sein.",
        )
    if spec.unique and _value_taken(db, config.model, spec.name, value, exclude_id):
        return FieldError(spec.name, "Dieser Wert ist bereits vergeben.")
    return None


def _validate_forbidden_fields(
    config: CoreelementTypeConfig, data: CoreelementRequest
) -> list[FieldError]:
    allowed = {spec.name for spec in config.extra_fields}
    forbidden_msg = "Dieses Feld ist für diesen Typ nicht zulässig."
    errors = [
        FieldError(field_name, forbidden_msg)
        for field_name in ("label", "description", "address", "color")
        if field_name not in allowed and getattr(data, field_name) is not None
    ]
    if not config.has_active_field and data.active is not None:
        errors.append(FieldError("active", forbidden_msg))
    return errors


def _validate(
    db: Session,
    type_: CoreelementType,
    data: CoreelementRequest,
    exclude_id: uuid.UUID | None,
) -> list[FieldError]:
    config = COREELEMENT_CONFIG[type_]
    errors: list[FieldError] = []

    name_error = _validate_name(db, config, data.name.strip(), exclude_id)
    if name_error:
        errors.append(name_error)

    for spec in config.extra_fields:
        raw_value = getattr(data, spec.name)
        error = _validate_extra_field(
            db, config, spec, raw_value.strip() if raw_value else None, exclude_id
        )
        if error:
            errors.append(error)

    errors.extend(_validate_forbidden_fields(config, data))
    return errors


def _get_or_404(
    db: Session, model: type[CoreelementModel], element_id: uuid.UUID
) -> CoreelementModel:
    result = db.execute(select(model).where(model.id == element_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise CoreelementNotFoundError
    return obj


def list_coreelements(
    db: Session, type_: CoreelementType, *, active_only: bool = False
) -> Sequence[CoreelementModel]:
    """`active_only=True` restricts the result to currently-active rows --
    used by the "add a new position" pickers (Ordinariumwork/Performance
    setup editors, User form) so an archived Instrument/Voice/Choirjob is
    no longer offered there. A no-op for types without `active`
    (location/role/propriumelement): there's no active state to filter by,
    so every row is effectively "active". The admin Coreelement listing
    itself (GET /coreelements/{type}) deliberately never sets this --
    archived elements must stay visible/editable/reactivatable there."""
    config = COREELEMENT_CONFIG[type_]
    stmt = select(config.model).order_by(config.model.order, config.model.id)
    if active_only and config.has_active_field:
        active_model = cast("type[_ActiveCoreelementModel]", config.model)
        stmt = stmt.where(active_model.active == True)  # noqa: E712
    result = db.execute(stmt)
    return result.scalars().all()


def create_coreelement(
    db: Session, type_: CoreelementType, data: CoreelementRequest
) -> CoreelementModel:
    config = COREELEMENT_CONFIG[type_]
    errors = _validate(db, type_, data, exclude_id=None)
    if errors:
        raise CoreelementValidationError(errors)

    # max() over an empty table is NULL, so `(existing_max or 0) + 1` gives
    # the very first row of a type order 1.
    existing_max = db.execute(select(func.max(config.model.order))).scalar_one()
    obj = config.model(
        name=data.name.strip(),
        order=(existing_max or 0) + 1,
    )
    for spec in config.extra_fields:
        setattr(obj, spec.name, getattr(data, spec.name).strip())
    if config.has_active_field:
        # New elements start active unless the caller explicitly says
        # otherwise -- omitting the field is the common case (the admin
        # form always defaults its checkbox to checked).
        cast("_ActiveCoreelementModel", obj).active = (
            True if data.active is None else data.active
        )

    db.add(obj)
    db.commit()
    return obj


def update_coreelement(
    db: Session, type_: CoreelementType, element_id: uuid.UUID, data: CoreelementRequest
) -> CoreelementModel:
    config = COREELEMENT_CONFIG[type_]
    obj = _get_or_404(db, config.model, element_id)
    errors = _validate(db, type_, data, exclude_id=element_id)
    if errors:
        raise CoreelementValidationError(errors)

    # An update never touches `order` -- reordering only happens through
    # the dedicated move endpoint below.
    obj.name = data.name.strip()
    for spec in config.extra_fields:
        setattr(obj, spec.name, getattr(data, spec.name).strip())
    if config.has_active_field and data.active is not None:
        # Omitting the field preserves the current value -- unlike create,
        # an update must never silently reset an archived element back to
        # active just because the caller didn't send the field.
        cast("_ActiveCoreelementModel", obj).active = data.active
    db.commit()
    return obj


def delete_coreelement(
    db: Session, type_: CoreelementType, element_id: uuid.UUID
) -> None:
    config = COREELEMENT_CONFIG[type_]
    obj = _get_or_404(db, config.model, element_id)
    if config.has_dependencies is not None and config.has_dependencies(db, obj):
        raise CoreelementInUseError
    db.delete(obj)
    db.commit()


def move_coreelement(
    db: Session,
    type_: CoreelementType,
    element_id: uuid.UUID,
    direction: Literal["up", "down"],
) -> Sequence[CoreelementModel]:
    """Two-row order swap (only the two affected rows are written, the rest
    of the list is never reindexed). No-op at either boundary of the
    list."""
    items = list(list_coreelements(db, type_))
    index = next((i for i, item in enumerate(items) if item.id == element_id), None)
    if index is None:
        raise CoreelementNotFoundError

    neighbor_index = index - 1 if direction == "up" else index + 1
    if not 0 <= neighbor_index < len(items):
        return items

    current, neighbor = items[index], items[neighbor_index]
    current.order, neighbor.order = neighbor.order, current.order
    db.commit()
    return list_coreelements(db, type_)
