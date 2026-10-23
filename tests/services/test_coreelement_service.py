import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.db.models.role import Role
from app.schemas.coreelement import CoreelementRequest, CoreelementType
from app.schemas.pagination import MAX_PAGE_SIZE, PageParams
from app.services import coreelement_service
from tests.sql_capture import recorded_statements

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _unique(base: str = "Element") -> str:
    """Every test gets its own collision-free name -- tests/conftest.py's
    shared test DB has no per-test rollback (same reason as make_user's
    uuid-based emails), and coreelement names are globally unique
    per type, unlike Users."""
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _request(
    name: str | None = None,
    *,
    label: str | None = None,
    description: str | None = None,
    address: str | None = None,
    color: str | None = None,
    active: bool | None = None,
) -> CoreelementRequest:
    return CoreelementRequest(
        name=name or _unique(),
        label=label,
        description=description,
        address=address,
        color=color,
        active=active,
    )


class TestListCoreelements:
    def test_unknown_type_key_returns_only_matching_rows(self, db_session: Session):
        marker = _unique("Marker")
        coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request(marker)
        )
        items = coreelement_service.list_coreelements(db_session, CoreelementType.voice)
        assert marker not in [item.name for item in items]

    def test_new_items_are_adjacent_in_order(self, db_session: Session):
        first_name, second_name = _unique("Fagott"), _unique("Oboe")
        coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request(first_name)
        )
        coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request(second_name)
        )
        items = coreelement_service.list_coreelements(
            db_session, CoreelementType.instrument
        )
        names = [item.name for item in items]
        assert names.index(first_name) + 1 == names.index(second_name)

    def test_active_only_excludes_archived_instruments(self, db_session: Session):
        active_item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request()
        )
        archived_item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request(active=False)
        )

        ids = [
            item.id
            for item in coreelement_service.list_coreelements(
                db_session, CoreelementType.instrument, active_only=True
            )
        ]

        assert active_item.id in ids
        assert archived_item.id not in ids

    def test_active_only_is_a_noop_for_types_without_the_field(
        self, db_session: Session
    ):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.propriumelement, _request()
        )

        ids = [
            i.id
            for i in coreelement_service.list_coreelements(
                db_session, CoreelementType.propriumelement, active_only=True
            )
        ]

        assert item.id in ids


class TestCreateCoreelement:
    def test_simple_type_assigns_strictly_incrementing_order(self, db_session: Session):
        first = coreelement_service.create_coreelement(
            db_session, CoreelementType.voice, _request()
        )
        second = coreelement_service.create_coreelement(
            db_session, CoreelementType.voice, _request()
        )
        assert second.order == first.order + 1

    def test_name_too_short_is_rejected(self):
        # Now caught by CoreelementRequest's own Field(min_length=3)
        # before the service's _validate_name() ever runs -- the schema
        # boundary was tightened to match the service's pre-existing
        # 3-character floor (shared by all six types).
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(min_length=3)
            _request("ab")

    def test_duplicate_name_is_rejected(self, db_session: Session):
        name = _unique("Substitut")
        coreelement_service.create_coreelement(
            db_session, CoreelementType.choirjob, _request(name)
        )
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session, CoreelementType.choirjob, _request(name)
            )
        assert exc_info.value.errors == [("name", "Der Name ist bereits vergeben.")]

    def test_role_enforces_shorter_name_max_length(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session,
                CoreelementType.role,
                _request("a-name-longer-than-16", label="Label", description="Desc"),
            )
        assert exc_info.value.errors == [
            ("name", "Muss zwischen 3 und 16 Zeichen lang sein.")
        ]

    def test_role_requires_label_and_description(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session, CoreelementType.role, _request(_unique("r")[:16])
            )
        assert exc_info.value.errors == [
            ("label", "Dieses Feld ist erforderlich."),
            ("description", "Dieses Feld ist erforderlich."),
        ]

    def test_role_label_uniqueness_enforced(self, db_session: Session):
        label = _unique("Noten")
        coreelement_service.create_coreelement(
            db_session,
            CoreelementType.role,
            _request(_unique("r")[:16], label=label, description="Notenverwaltung"),
        )
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session,
                CoreelementType.role,
                _request(
                    _unique("r")[:16], label=label, description="Andere Beschreibung"
                ),
            )
        assert exc_info.value.errors == [("label", "Dieser Wert ist bereits vergeben.")]

    def test_location_requires_address_and_color(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session, CoreelementType.location, _request()
            )
        assert exc_info.value.errors == [
            ("address", "Dieses Feld ist erforderlich."),
            ("color", "Dieses Feld ist erforderlich."),
        ]

    def test_location_succeeds_with_all_fields(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.location,
            _request(address="Hauptstraße 1", color="ff0000"),
        )
        assert (item.address, item.color) == ("Hauptstraße 1", "ff0000")

    def test_forbidden_extra_field_for_simple_type_is_rejected(
        self, db_session: Session
    ):
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session,
                CoreelementType.instrument,
                _request(label="Sollte nicht erlaubt sein"),
            )
        assert exc_info.value.errors == [
            ("label", "Dieses Feld ist für diesen Typ nicht zulässig.")
        ]


class TestUpdateCoreelement:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementNotFoundError):
            coreelement_service.update_coreelement(
                db_session, CoreelementType.instrument, uuid.uuid4(), _request()
            )

    def test_updates_name_without_changing_order(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request()
        )
        original_order = item.order
        new_name = _unique("Querflöte")

        updated = coreelement_service.update_coreelement(
            db_session, CoreelementType.instrument, item.id, _request(new_name)
        )

        assert updated.name == new_name
        assert updated.order == original_order

    def test_keeping_own_name_does_not_trigger_uniqueness_error(
        self, db_session: Session
    ):
        name = _unique("Trompete")
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request(name)
        )
        updated = coreelement_service.update_coreelement(
            db_session, CoreelementType.instrument, item.id, _request(name)
        )
        assert updated.name == name

    def test_duplicate_name_against_other_row_is_rejected(self, db_session: Session):
        taken_name = _unique("Horn")
        coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request(taken_name)
        )
        second = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request()
        )
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.update_coreelement(
                db_session, CoreelementType.instrument, second.id, _request(taken_name)
            )
        assert exc_info.value.errors == [("name", "Der Name ist bereits vergeben.")]

    def test_updates_extra_fields(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.location,
            _request(address="Alte Adresse 1", color="000000"),
        )

        updated = coreelement_service.update_coreelement(
            db_session,
            CoreelementType.location,
            item.id,
            _request(item.name, address="Neue Adresse 2", color="00ff00"),
        )

        assert (updated.address, updated.color) == ("Neue Adresse 2", "00ff00")

    def test_extra_field_out_of_bounds_is_rejected(self):
        # Now caught by CoreelementRequest's own Field(min_length=3) on
        # `address` before the service's _validate_extra_field() ever
        # runs -- address is used by exactly one type (Location), so the
        # schema bound here IS the service's exact 3-60 constant, not just
        # a best-effort outer net (see CoreelementRequest's docstring).
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(min_length=3)
            _request(address="ab", color="000000")


class TestDeleteCoreelement:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementNotFoundError):
            coreelement_service.delete_coreelement(
                db_session, CoreelementType.instrument, uuid.uuid4()
            )

    def test_unreferenced_element_can_be_deleted(self, db_session: Session):
        """An element nothing references can always be deleted, and a second
        delete then reports it as not found."""
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request()
        )
        coreelement_service.delete_coreelement(
            db_session, CoreelementType.instrument, item.id
        )

        with pytest.raises(coreelement_service.CoreelementNotFoundError):
            coreelement_service.delete_coreelement(
                db_session, CoreelementType.instrument, item.id
            )

    def test_role_delete_blocked_when_users_assigned(
        self, db_session: Session, make_user
    ):
        role_name = _unique("r")[:16]
        role = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.role,
            _request(role_name, label=_unique("Noten"), description="Notenverwaltung"),
        )
        make_user(roles=[role_name])

        with pytest.raises(coreelement_service.CoreelementInUseError):
            coreelement_service.delete_coreelement(
                db_session, CoreelementType.role, role.id
            )

    def test_role_delete_succeeds_without_assigned_users(self, db_session: Session):
        role = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.role,
            _request(
                _unique("r")[:16], label=_unique("Kurz-URLs"), description="Kurz-URLs"
            ),
        )
        coreelement_service.delete_coreelement(
            db_session, CoreelementType.role, role.id
        )

        with pytest.raises(coreelement_service.CoreelementNotFoundError):
            coreelement_service.delete_coreelement(
                db_session, CoreelementType.role, role.id
            )


def _permission_role(db_session: Session, name: str = "planner") -> Role:
    """The role row of the permission matrix, with no user assigned (an
    assigned role could not be deleted for that reason alone)."""
    role = db_session.execute(
        select(Role).where(Role.name == name)
    ).scalar_one_or_none()
    if role is None:
        role = Role(
            name=name, label=f"Label {name}", description=f"Beschreibung {name}"
        )
        db_session.add(role)
        db_session.commit()
    return role


class TestLocationColor:
    @pytest.mark.parametrize("color", ["abc", "zzzzzz", "12345g", "red", "12345"])
    def test_create_rejects_a_value_that_is_not_six_hex_digits(
        self, db_session: Session, color: str
    ):
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session,
                CoreelementType.location,
                _request(address="Hauptstraße 1", color=color),
            )

        assert [field for field, _ in exc_info.value.errors] == ["color"]

    @pytest.mark.parametrize("color", ["ff0000", "00FF7f", "123456"])
    def test_create_accepts_six_hex_digits(self, db_session: Session, color: str):
        item = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.location,
            _request(address="Hauptstraße 1", color=color),
        )

        assert item.color == color

    def test_update_rejects_a_value_that_is_not_six_hex_digits(
        self, db_session: Session
    ):
        item = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.location,
            _request(address="Hauptstraße 1", color="ff0000"),
        )

        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.update_coreelement(
                db_session,
                CoreelementType.location,
                item.id,
                _request(item.name, address="Hauptstraße 1", color="red"),
            )

        assert [field for field, _ in exc_info.value.errors] == ["color"]


class TestPermissionRoles:
    def test_renaming_a_role_of_the_permission_matrix_is_refused(
        self, db_session: Session
    ):
        role = _permission_role(db_session)

        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.update_coreelement(
                db_session,
                CoreelementType.role,
                role.id,
                _request("planer", label="Planer", description="Planung"),
            )

        assert [field for field, _ in exc_info.value.errors] == ["name"]
        db_session.refresh(role)
        assert role.name == "planner"

    def test_label_and_description_of_such_a_role_stay_editable(
        self, db_session: Session
    ):
        role = _permission_role(db_session)

        updated = coreelement_service.update_coreelement(
            db_session,
            CoreelementType.role,
            role.id,
            _request(" planner ", label="Planung neu", description="Neue Beschreibung"),
        )

        assert (updated.name, updated.label, updated.description) == (
            "planner",
            "Planung neu",
            "Neue Beschreibung",
        )

    @pytest.mark.parametrize(
        "name", ["billing", "disponent", "planner", "scores", "shorturls"]
    )
    def test_deleting_a_role_of_the_permission_matrix_is_refused(
        self, db_session: Session, name: str
    ):
        role = _permission_role(db_session, name)

        with pytest.raises(coreelement_service.GeneralValidationError) as exc_info:
            coreelement_service.delete_coreelement(
                db_session, CoreelementType.role, role.id
            )

        assert exc_info.type is coreelement_service.GeneralValidationError
        assert db_session.get(Role, role.id) is not None

    def test_another_role_can_still_be_renamed(self, db_session: Session):
        role = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.role,
            _request(_unique("r")[:16], label=_unique("Alt"), description="Alt"),
        )

        new_name = _unique("n")[:16]

        updated = coreelement_service.update_coreelement(
            db_session,
            CoreelementType.role,
            role.id,
            _request(new_name, label=_unique("Neu"), description="Neue Beschreibung"),
        )

        assert updated.name == new_name

    def test_a_non_role_type_with_the_same_name_is_not_protected(
        self, db_session: Session
    ):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request("planner")
        )

        coreelement_service.delete_coreelement(
            db_session, CoreelementType.instrument, item.id
        )


class TestOrderLock:
    def test_create_takes_the_advisory_lock_before_it_reads_the_maximum(
        self, db_session: Session
    ):
        with recorded_statements() as statements:
            coreelement_service.create_coreelement(
                db_session, CoreelementType.instrument, _request()
            )

        assert "pg_advisory_xact_lock" in statements[0]
        assert any("max(" in s.lower() for s in statements[1:])

    def test_move_takes_the_advisory_lock_first(self, db_session: Session):
        first = coreelement_service.create_coreelement(
            db_session, CoreelementType.voice, _request()
        )
        first_id = first.id

        with recorded_statements() as statements:
            coreelement_service.move_coreelement(
                db_session, CoreelementType.voice, first_id, "down"
            )

        assert "pg_advisory_xact_lock" in statements[0]

    def test_update_and_listing_take_no_lock(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.choirjob, _request()
        )

        with recorded_statements() as statements:
            coreelement_service.update_coreelement(
                db_session, CoreelementType.choirjob, item.id, _request(item.name)
            )
            coreelement_service.list_coreelements(db_session, CoreelementType.choirjob)

        assert all("pg_advisory_xact_lock" not in s for s in statements)


class TestMoveCoreelement:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementNotFoundError):
            coreelement_service.move_coreelement(
                db_session, CoreelementType.instrument, uuid.uuid4(), "up"
            )

    def test_move_up_swaps_with_previous_item(self, db_session: Session):
        first = coreelement_service.create_coreelement(
            db_session, CoreelementType.propriumelement, _request()
        )
        second = coreelement_service.create_coreelement(
            db_session, CoreelementType.propriumelement, _request()
        )
        first_order, second_order = first.order, second.order

        coreelement_service.move_coreelement(
            db_session, CoreelementType.propriumelement, second.id, "up"
        )

        assert (first.order, second.order) == (second_order, first_order)

    def test_move_up_at_top_is_a_no_op(self, db_session: Session):
        """Whichever row is currently first for this type (regardless of
        which test created it -- tests/conftest.py's shared test DB
        has no per-test rollback), moving it further up must be a no-op."""
        coreelement_service.create_coreelement(
            db_session, CoreelementType.propriumelement, _request()
        )
        top_item = coreelement_service.list_coreelements(
            db_session, CoreelementType.propriumelement
        )[0]
        original_order = top_item.order

        coreelement_service.move_coreelement(
            db_session, CoreelementType.propriumelement, top_item.id, "up"
        )

        assert top_item.order == original_order

    def test_move_down_at_bottom_is_a_no_op(self, db_session: Session):
        coreelement_service.create_coreelement(
            db_session, CoreelementType.propriumelement, _request()
        )
        second = coreelement_service.create_coreelement(
            db_session, CoreelementType.propriumelement, _request()
        )
        original_order = second.order

        coreelement_service.move_coreelement(
            db_session, CoreelementType.propriumelement, second.id, "down"
        )

        assert second.order == original_order


class TestActiveField:
    def test_create_defaults_to_active_true(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request()
        )
        assert item.active is True

    def test_create_respects_explicit_false(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.voice, _request(active=False)
        )
        assert item.active is False

    def test_update_preserves_active_when_omitted(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.choirjob, _request(active=False)
        )

        updated = coreelement_service.update_coreelement(
            db_session, CoreelementType.choirjob, item.id, _request(item.name)
        )

        assert updated.active is False

    def test_update_can_reactivate(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.instrument, _request(active=False)
        )

        updated = coreelement_service.update_coreelement(
            db_session,
            CoreelementType.instrument,
            item.id,
            _request(item.name, active=True),
        )

        assert updated.active is True

    def test_forbidden_for_types_without_the_field(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session, CoreelementType.propriumelement, _request(active=True)
            )
        assert exc_info.value.errors == [
            ("active", "Dieses Feld ist für diesen Typ nicht zulässig.")
        ]


class TestToResponse:
    def test_role_carries_label_and_description_only(self, db_session: Session):
        role = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.role,
            _request(
                _unique("Rolle")[:16],
                label=_unique("Label"),
                description="Beschreibung der Rolle",
            ),
        )

        response = coreelement_service.to_response(role)

        assert response.id == role.id
        assert response.name == role.name
        assert response.order == role.order
        assert response.label == role.label
        assert response.description == "Beschreibung der Rolle"
        assert response.address is None
        assert response.color is None
        assert response.active is None

    def test_location_carries_address_and_color_only(self, db_session: Session):
        location = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.location,
            _request(address="Hauptstraße 1", color="ff0000"),
        )

        response = coreelement_service.to_response(location)

        assert response.address == "Hauptstraße 1"
        assert response.color == "ff0000"
        assert response.label is None
        assert response.description is None
        assert response.active is None

    @pytest.mark.parametrize("active", [True, False])
    @pytest.mark.parametrize(
        "type_",
        [CoreelementType.instrument, CoreelementType.voice, CoreelementType.choirjob],
    )
    def test_archivable_types_carry_the_active_flag(
        self, db_session: Session, type_: CoreelementType, active: bool
    ):
        item = coreelement_service.create_coreelement(
            db_session, type_, _request(active=active)
        )

        response = coreelement_service.to_response(item)

        assert response.active is active
        assert response.label is None
        assert response.address is None

    def test_propriumelement_has_none_of_the_optional_attributes(
        self, db_session: Session
    ):
        item = coreelement_service.create_coreelement(
            db_session, CoreelementType.propriumelement, _request()
        )

        response = coreelement_service.to_response(item)

        assert (
            response.label,
            response.description,
            response.address,
            response.color,
            response.active,
        ) == (None, None, None, None, None)

    def test_mapping_a_page_of_roles_adds_no_statements(self, db_session: Session):
        for _ in range(3):
            coreelement_service.create_coreelement(
                db_session,
                CoreelementType.role,
                _request(
                    _unique("Rolle")[:16],
                    label=_unique("Label"),
                    description="Beschreibung der Rolle",
                ),
            )
        paged = coreelement_service.list_coreelements_page(
            db_session, CoreelementType.role, PageParams(limit=MAX_PAGE_SIZE, offset=0)
        )

        with recorded_statements() as statements:
            paged.map(coreelement_service.to_response)

        assert statements == []
