import uuid

import pytest
from sqlalchemy.orm import Session

from app.schemas.coreelement import CoreelementRequest, CoreelementType
from app.services import coreelement_service


def _unique(base: str = "Element") -> str:
    """Every test gets its own collision-free name -- tests/conftest.py's
    shared test DB has no per-test rollback (1:1 make_user's uuid-based
    emails for the same reason), and coreelement names are globally unique
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

    def test_name_too_short_is_rejected(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.create_coreelement(
                db_session, CoreelementType.instrument, _request("ab")
            )
        assert exc_info.value.errors == [
            ("name", "Muss zwischen 3 und 60 Zeichen lang sein.")
        ]

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
                db_session, CoreelementType.instrument, 999, _request()
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

    def test_extra_field_out_of_bounds_is_rejected(self, db_session: Session):
        item = coreelement_service.create_coreelement(
            db_session,
            CoreelementType.location,
            _request(address="Alte Adresse 1", color="000000"),
        )
        with pytest.raises(coreelement_service.CoreelementValidationError) as exc_info:
            coreelement_service.update_coreelement(
                db_session,
                CoreelementType.location,
                item.id,
                _request(item.name, address="ab", color="000000"),
            )
        assert exc_info.value.errors == [
            ("address", "Muss zwischen 3 und 60 Zeichen lang sein.")
        ]


class TestDeleteCoreelement:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementNotFoundError):
            coreelement_service.delete_coreelement(
                db_session, CoreelementType.instrument, 999
            )

    def test_simple_type_has_no_dependency_check_yet(self, db_session: Session):
        """Instrument/Voice/Choirjob/Location/Propriumelement have zero real
        dependents in osa-backend today (Performance/Repertoire domains
        don't exist until Schritt 4/5) -- delete must always succeed."""
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


class TestMoveCoreelement:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(coreelement_service.CoreelementNotFoundError):
            coreelement_service.move_coreelement(
                db_session, CoreelementType.instrument, 999, "up"
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
