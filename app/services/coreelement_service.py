from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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

CoreelementModel = Instrument | Voice | Choirjob | Location | Propriumelement | Role
# The subset of CoreelementModel that actually has an `active` column --
# narrows config.model back down wherever has_active_field guards the
# access at runtime (Location/Propriumelement/Role don't have this
# attribute, so a plain access would fail pyright strict).
_ActiveCoreelementModel = Instrument | Voice | Choirjob


class CoreelementNotFoundError(Exception):
    """Raised when `element_id` doesn't exist for the given CoreelementType."""


class CoreelementValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's per-type
    SaveRequest error bags -- 1:1 auth_service.RegistrationConflictError
    pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Coreelement validation failed")


class CoreelementInUseError(Exception):
    """Raised when delete is blocked by a dependent row -- mirrors
    Legacy's HasDependencies check (DestroyRequest::withValidator)."""


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
    """Only Role had a real dependency target from the start (`user_roles`,
    built in Schritt 2/Auth)."""
    count = db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
    ).scalar_one()
    return count > 0


def _make_position_dependency_check(
    position_type: str,
) -> Callable[[Session, CoreelementModel], bool]:
    """Instrument/Voice/Choirjob can be referenced by an Ordinariumwork's
    Positions setup (Schritt 4 -- choirjobs never actually match here,
    excluded by ordinariumwork_positions' own CHECK constraint, so that
    query is simply always empty for position_type='choirjobs') AND/OR a
    Performance's Positions setup (Schritt 5, all three types). Legacy's
    own Instrument/Voice/Choirjob $dependencies also list `users`
    (user_positions) -- that table doesn't exist in osa-backend yet (User
    domain, a later Schritt), deferred the same way this check itself was
    deferred before Schritt 4/5 landed."""

    def _check(db: Session, item: CoreelementModel) -> bool:
        ordinariumwork_count = db.execute(
            select(func.count())
            .select_from(OrdinariumworkPosition)
            .where(
                OrdinariumworkPosition.position_type == position_type,
                OrdinariumworkPosition.position_id == item.id,
            )
        ).scalar_one()
        performance_count = db.execute(
            select(func.count())
            .select_from(PerformancePosition)
            .where(
                PerformancePosition.position_type == position_type,
                PerformancePosition.position_id == item.id,
            )
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
    exclude_id: int | None,
) -> bool:
    column = getattr(model, field_name)
    stmt = select(model.id).where(column == value)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _validate_name(
    db: Session, config: CoreelementTypeConfig, name: str, exclude_id: int | None
) -> tuple[str, str] | None:
    if not 3 <= len(name) <= config.name_max_length:
        return (
            "name",
            f"Muss zwischen 3 und {config.name_max_length} Zeichen lang sein.",
        )
    if _value_taken(db, config.model, "name", name, exclude_id):
        return "name", "Der Name ist bereits vergeben."
    return None


def _validate_extra_field(
    db: Session,
    config: CoreelementTypeConfig,
    spec: FieldSpec,
    value: str | None,
    exclude_id: int | None,
) -> tuple[str, str] | None:
    if value is None:
        return spec.name, "Dieses Feld ist erforderlich."
    if not spec.min_length <= len(value) <= spec.max_length:
        return (
            spec.name,
            f"Muss zwischen {spec.min_length} und {spec.max_length} Zeichen lang sein.",
        )
    if spec.unique and _value_taken(db, config.model, spec.name, value, exclude_id):
        return spec.name, "Dieser Wert ist bereits vergeben."
    return None


def _validate_forbidden_fields(
    config: CoreelementTypeConfig, data: CoreelementRequest
) -> list[tuple[str, str]]:
    allowed = {spec.name for spec in config.extra_fields}
    forbidden_msg = "Dieses Feld ist für diesen Typ nicht zulässig."
    errors = [
        (field_name, forbidden_msg)
        for field_name in ("label", "description", "address", "color")
        if field_name not in allowed and getattr(data, field_name) is not None
    ]
    if not config.has_active_field and data.active is not None:
        errors.append(("active", forbidden_msg))
    return errors


def _validate(
    db: Session,
    type_: CoreelementType,
    data: CoreelementRequest,
    exclude_id: int | None,
) -> list[tuple[str, str]]:
    config = COREELEMENT_CONFIG[type_]
    errors: list[tuple[str, str]] = []

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
    db: Session, model: type[CoreelementModel], element_id: int
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

    # (existing_max or 0) + 1 mirrors Legacy's `<Model>::max('order') + 1`
    # exactly, including its NULL-on-empty-table quirk (PHP coerces
    # null + 1 to 1, not 0, for the very first row of a type).
    existing_max = db.execute(select(func.max(config.model.order))).scalar_one()
    now = datetime.now(UTC)
    obj = config.model(
        name=data.name.strip(),
        order=(existing_max or 0) + 1,
        created_at=now,
        updated_at=now,
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
    db: Session, type_: CoreelementType, element_id: int, data: CoreelementRequest
) -> CoreelementModel:
    config = COREELEMENT_CONFIG[type_]
    obj = _get_or_404(db, config.model, element_id)
    errors = _validate(db, type_, data, exclude_id=element_id)
    if errors:
        raise CoreelementValidationError(errors)

    # Legacy's update() never touches `order` -- reordering only happens
    # through the dedicated move endpoint below.
    obj.name = data.name.strip()
    for spec in config.extra_fields:
        setattr(obj, spec.name, getattr(data, spec.name).strip())
    if config.has_active_field and data.active is not None:
        # Omitting the field preserves the current value -- unlike create,
        # an update must never silently reset an archived element back to
        # active just because the caller didn't send the field.
        cast("_ActiveCoreelementModel", obj).active = data.active
    obj.updated_at = datetime.now(UTC)
    db.commit()
    return obj


def delete_coreelement(db: Session, type_: CoreelementType, element_id: int) -> None:
    config = COREELEMENT_CONFIG[type_]
    obj = _get_or_404(db, config.model, element_id)
    if config.has_dependencies is not None and config.has_dependencies(db, obj):
        raise CoreelementInUseError
    db.delete(obj)
    db.commit()


def move_coreelement(
    db: Session,
    type_: CoreelementType,
    element_id: int,
    direction: Literal["up", "down"],
) -> Sequence[CoreelementModel]:
    """Two-row order swap, replacing Legacy's HasCoreelementFeatures::move()
    (loads the entire table, then reindexes and re-saves EVERY row on
    every single click -- an O(n) anti-pattern flagged for modernization,
    see project_osa_legacy_domain_map memory). No-op at either boundary,
    mirroring Legacy's disabled up/down buttons at the list's ends."""
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
