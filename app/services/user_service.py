from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.datetime_utils import local_now
from app.core.human_names import normalize_givenname, normalize_surname
from app.db.models.booking import Booking
from app.db.models.oauth2_binding import Oauth2Binding
from app.db.models.performance import Performance
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.schemas.coreelement import CoreelementType
from app.schemas.performance import PositionRefOutput
from app.schemas.user import (
    Oauth2BindingOutput,
    RoleRefOutput,
    UserFormOptionsOutput,
    UserRequest,
    UserResponse,
)
from app.services import coreelement_service
from app.services.position_types import POSITION_MODELS, PositionType
from app.services.user_position_service import (
    get_position_ids_for_user,
    sync_user_positions,
)

if TYPE_CHECKING:
    from app.db.models.role import Role

_SEARCH_RESULT_LIMIT = 20


class UserNotFoundError(Exception):
    """Raised when `user_id` doesn't exist among non-deleted users -- 1:1
    Legacy's implicit route-model-binding on a SoftDeletes model without
    `->withTrashed()` (System::UserController, unlike
    Administrator::UserAdministrationController, see
    user_administration_service.py)."""


class UserValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 fee_service.FeeValidationError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("User validation failed")


class AdministratorProtectedError(Exception):
    """update/destroy targeting a user with administrator=True -- 1:1
    Legacy's `abort_if($user->administrator, 501, ...)` in
    System::UserController::update()/destroy(). No exception even when the
    acting user is themselves an administrator."""


class UserInUseError(Exception):
    """delete blocked because deletable is False -- see _is_deletable()."""


def _position_refs_for_user(
    db: Session, position_ids: dict[PositionType, set[int]], position_type: PositionType
) -> list[PositionRefOutput]:
    ids = position_ids[position_type]
    if not ids:
        return []
    model = POSITION_MODELS[position_type]
    rows = (
        db.execute(
            select(model).where(model.id.in_(ids)).order_by(model.order, model.id)
        )
        .scalars()
        .all()
    )
    return [PositionRefOutput(id=row.id, name=row.name) for row in rows]


def _is_deletable(db: Session, user_id: int) -> bool:
    """`!(hasDependencies || upcoming confirmed bookings)`. Legacy's
    HasDependencies trait on User only lists `roles` (NOT the Instrument/
    Voice/Choirjob assignments in `user_positions`) -- an assigned
    Instrument alone never blocks delete. `requestsAndBookings(true, true)`
    (upcomingOnly, bookingsOnly) additionally blocks delete for a future
    CONFIRMED Booking -- an open BookingRequest without a Booking does
    NOT block it."""
    has_role = (
        db.execute(
            select(func.count())
            .select_from(UserRole)
            .where(UserRole.user_id == user_id)
        ).scalar_one()
        > 0
    )
    if has_role:
        return False

    has_future_booking = (
        db.execute(
            select(func.count())
            .select_from(Booking)
            .join(Performance, Performance.id == Booking.performance_id)
            .where(Booking.user_id == user_id, Performance.schedule > local_now())
        ).scalar_one()
        > 0
    )
    return not has_future_booking


def _to_response(db: Session, user: User) -> UserResponse:
    """Covers Show AND the Edit-form's prefill -- see UserResponse
    docstring. `user.roles` must already be eager-loaded (see
    _get_or_404's selectinload) to avoid a lazy-load outside the request's
    session."""
    position_ids = get_position_ids_for_user(db, user.id)
    roles = sorted(user.roles, key=lambda role: (role.order, role.id))
    oauth2_bindings = (
        db.execute(select(Oauth2Binding).where(Oauth2Binding.local_id == user.id))
        .scalars()
        .all()
    )

    return UserResponse(
        id=user.id,
        surname=user.surname,
        givenname=user.givenname,
        email=user.email,
        email_verified_at=user.email_verified_at,
        phone=user.phone,
        auth_lastsignal=user.auth_lastsignal,
        auth_locked=user.auth_locked,
        administrator=user.administrator,
        # An administrator is never deletable, regardless of roles/bookings.
        deletable=not user.administrator and _is_deletable(db, user.id),
        oauth2_bindings=[
            Oauth2BindingOutput(id=b.id, provider=b.provider, remote_name=b.remote_name)
            for b in oauth2_bindings
        ],
        instruments=_position_refs_for_user(db, position_ids, "instruments"),
        voices=_position_refs_for_user(db, position_ids, "voices"),
        choirjobs=_position_refs_for_user(db, position_ids, "choirjobs"),
        roles=[
            RoleRefOutput(id=role.id, name=role.name, label=role.label)
            for role in roles
        ],
    )


def _get_or_404(db: Session, user_id: int) -> User:
    result = db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise UserNotFoundError
    return user


def search_users(db: Session, query: str) -> Sequence[User]:
    """Real indexed DB query, replacing Legacy's `User::search()`
    in-memory-filter anti-pattern -- 1:1 artist_service.search_artists.
    Matches against "SURNAME, Givenname" (with the comma), mirroring
    Legacy's `Str::containsAll(strtolower($user->name))` against the
    HasHumanNames `name` virtual attribute. Excludes soft-deleted users --
    Administrator::UserAdministrationController has the withTrashed()
    variant (user_administration_service.py)."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return []

    combined_name = func.lower(User.surname + ", " + User.givenname)
    stmt = (
        select(User)
        .where(
            User.deleted_at.is_(None),
            *[combined_name.like(f"%{word}%") for word in words],
        )
        .order_by(User.surname, User.givenname)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    return db.execute(stmt).scalars().all()


def get_user(db: Session, user_id: int) -> UserResponse:
    user = _get_or_404(db, user_id)
    return _to_response(db, user)


def get_form_options(db: Session) -> UserFormOptionsOutput:
    """Catalog lists for the form's Instrument/Voice/Choirjob/Role picker
    widgets -- reuses coreelement_service.list_coreelements() directly
    (that function has no permission logic of its own, the gating happens
    only in its own router), rather than calling the /coreelements/{type}
    HTTP endpoints, which would wrongly require instrumentMaintain/
    voiceMaintain/... instead of userMaintain for a Disponent."""

    def _refs(type_: CoreelementType) -> list[PositionRefOutput]:
        # active_only=True: an archived Instrument/Voice/Choirjob must not
        # be offered for a NEW assignment here. A user who already has one
        # assigned still sees it correctly -- get_user()/the User's own
        # `instruments`/`voices`/`choirjobs` are resolved separately, by
        # id, not through this picker list.
        return [
            PositionRefOutput(id=item.id, name=item.name)
            for item in coreelement_service.list_coreelements(
                db, type_, active_only=True
            )
        ]

    # CoreelementType.role always yields Role instances -- list_coreelements()'s
    # return type is the full CoreelementModel union since it's generic over
    # all six types, cast narrows it back for the .label access below.
    roles = cast(
        "Sequence[Role]",
        coreelement_service.list_coreelements(db, CoreelementType.role),
    )
    return UserFormOptionsOutput(
        instruments=_refs(CoreelementType.instrument),
        voices=_refs(CoreelementType.voice),
        choirjobs=_refs(CoreelementType.choirjob),
        roles=[
            RoleRefOutput(id=role.id, name=role.name, label=role.label)
            for role in roles
        ],
    )


def _name_combo_taken(
    db: Session, surname: str, givenname: str, exclude_id: int | None
) -> bool:
    # No deleted_at filter -- `UniqueConstraint("surname", "givenname")` on
    # the users table itself is unconditional (spans soft-deleted rows
    # too), so a pre-check that ignored them could still hit a raw
    # IntegrityError at commit time.
    stmt = select(User.id).where(User.surname == surname, User.givenname == givenname)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _email_taken(db: Session, email: str, exclude_id: int | None) -> bool:
    # Same reasoning as _name_combo_taken -- users.email's unique index is
    # unconditional too.
    stmt = select(User.id).where(User.email == email)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _validate(
    db: Session, data: UserRequest, exclude_id: int | None
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    surname = normalize_surname(data.surname)
    givenname = normalize_givenname(data.givenname)
    if _name_combo_taken(db, surname, givenname, exclude_id):
        msg = "Die Kombination von Vor- und Nachname ist vergeben."
        errors.append(("surname", msg))
        errors.append(("givenname", msg))
    if data.email is not None and _email_taken(db, data.email, exclude_id):
        errors.append(("email", "Diese E-Mail-Adresse ist bereits vergeben."))
    return errors


def _apply_administrator_grant(
    user: User, *, desired: bool, current_user: User
) -> None:
    """The administrator flag may only be GRANTED by a real administrator --
    1:1 the roles pattern (_sync_roles_if_administrator), a silent no-op for
    anyone else. Deliberately one-way: revoking is not implemented here
    because it's unreachable through the app anyway -- once granted, the
    target row is immediately protected by update_user()'s
    AdministratorProtectedError guard, matching Legacy's existing
    "administrators can not be updated" protection (Legacy itself has no
    path to grant the status in the first place; this is an intentional
    divergence)."""
    if desired and current_user.administrator:
        user.administrator = True


def _sync_roles_if_administrator(
    db: Session, user_id: int, role_ids: list[int], current_user: User
) -> None:
    """Roles may only be assigned/removed by a real administrator -- 1:1
    Legacy's System::UserController::save(): "this controller should be
    accessible by role:disponent and administrator. But roles must only be
    saved by administrator" -- a silent no-op for anyone else, not a
    validation error, since the field is accepted from every caller
    (defense-in-depth: the frontend already hides the Rollen picker from
    non-administrators, this is the server-side backstop)."""
    if not current_user.administrator:
        return

    existing = (
        db.execute(select(UserRole).where(UserRole.user_id == user_id)).scalars().all()
    )
    existing_ids = {user_role.role_id for user_role in existing}
    desired_ids = set(role_ids)

    for user_role in existing:
        if user_role.role_id not in desired_ids:
            db.delete(user_role)

    now = datetime.now(UTC)
    for role_id in desired_ids - existing_ids:
        db.add(
            UserRole(user_id=user_id, role_id=role_id, created_at=now, updated_at=now)
        )


def _sync_positions(db: Session, user_id: int, data: UserRequest) -> None:
    sync_user_positions(
        db,
        user_id=user_id,
        desired={
            "instruments": set(data.instruments),
            "voices": set(data.voices),
            "choirjobs": set(data.choirjobs),
        },
    )


def create_user(db: Session, data: UserRequest, current_user: User) -> UserResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise UserValidationError(errors)

    now = datetime.now(UTC)
    user = User(
        surname=normalize_surname(data.surname),
        givenname=normalize_givenname(data.givenname),
        email=data.email,
        phone=data.phone,
        auth_locked=data.auth_locked,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.flush()

    _apply_administrator_grant(
        user, desired=data.administrator, current_user=current_user
    )
    _sync_positions(db, user.id, data)
    _sync_roles_if_administrator(db, user.id, data.roles, current_user)

    db.commit()
    return get_user(db, user.id)


def update_user(
    db: Session, user_id: int, data: UserRequest, current_user: User
) -> UserResponse:
    user = _get_or_404(db, user_id)
    if user.administrator:
        raise AdministratorProtectedError

    errors = _validate(db, data, exclude_id=user_id)
    if errors:
        raise UserValidationError(errors)

    # Asymmetric with profile_service.update_profile() by design: an admin
    # changing someone ELSE's email resets verification but does NOT send a
    # new verification mail (1:1 Legacy quirk) -- only the user's own
    # Selfadmin-Profil edit does that.
    if data.email != user.email:
        user.email_verified_at = None

    user.surname = normalize_surname(data.surname)
    user.givenname = normalize_givenname(data.givenname)
    user.email = data.email
    user.phone = data.phone
    user.auth_locked = data.auth_locked
    user.updated_at = datetime.now(UTC)

    _apply_administrator_grant(
        user, desired=data.administrator, current_user=current_user
    )
    _sync_positions(db, user.id, data)
    _sync_roles_if_administrator(db, user.id, data.roles, current_user)

    db.commit()
    return get_user(db, user.id)


def delete_user(db: Session, user_id: int) -> None:
    user = _get_or_404(db, user_id)
    if user.administrator:
        raise AdministratorProtectedError
    if not _is_deletable(db, user_id):
        raise UserInUseError

    user.deleted_at = datetime.now(UTC)
    db.commit()
