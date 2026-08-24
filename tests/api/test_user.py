import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.artist import Artist
from app.db.models.booking import Booking
from app.db.models.choirjob import Choirjob
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance


def _unique(base: str = "User") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None, administrator: bool = False
) -> dict[str, str]:
    user = make_user(
        password="correct-password",
        roles=roles if roles is not None else ["disponent"],
        administrator=administrator,
    )
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_choirjob(db_session: Session) -> Choirjob:
    now = datetime.now(UTC)
    choirjob = Choirjob(
        name=_unique("Choirjob"), order=0, created_at=now, updated_at=now
    )
    db_session.add(choirjob)
    db_session.commit()
    return choirjob


def _make_past_performance(db_session: Session) -> Performance:
    now = datetime.now(UTC)
    artist = Artist(surname=_unique("Komponist"), givenname="Given", composer=True)
    location = Location(
        name=_unique("Ort"), order=0, address="Adresse 1", color="000000"
    )
    db_session.add_all([artist, location])
    db_session.flush()
    ordinariumwork = Ordinariumwork(
        name=_unique("Werk"), artist_id=artist.id, created_at=now, updated_at=now
    )
    db_session.add(ordinariumwork)
    db_session.flush()
    performance = Performance(
        schedule=datetime(2020, 1, 1, 11, 0, 0),  # noqa: DTZ001 -- naive wall-clock
        location_id=location.id,
        ordinariumwork_id=ordinariumwork.id,
        created_at=now,
        updated_at=now,
    )
    db_session.add(performance)
    db_session.commit()
    return performance


class TestPermissionGuard:
    def test_search_requires_authentication(self, client):
        response = client.get("/users/search", params={"q": "a"})
        assert response.status_code == 401

    def test_search_rejects_user_without_disponent_role_or_administrator(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get("/users/search", params={"q": "a"}, headers=headers)
        assert response.status_code == 403

    def test_search_allows_disponent(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=["disponent"])
        response = client.get("/users/search", params={"q": "a"}, headers=headers)
        assert response.status_code == 200

    def test_search_allows_administrator_without_disponent_role(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[], administrator=True)
        response = client.get("/users/search", params={"q": "a"}, headers=headers)
        assert response.status_code == 200

    def test_create_rejects_non_disponent(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.post(
            "/users",
            json={
                "givenname": "Max",
                "surname": _unique(),
                "email": None,
                "phone": None,
                "auth_locked": False,
                "instruments": [],
                "voices": [],
                "choirjobs": [],
                "roles": [],
            },
            headers=headers,
        )
        assert response.status_code == 403


class TestCrudRoundtrip:
    def test_create_show_edit_delete_user(self, client, make_user):
        headers = _auth_headers(client, make_user)
        surname = _unique("Muster")

        create_response = client.post(
            "/users",
            json={
                "givenname": "max",
                "surname": surname,
                "email": None,
                "phone": None,
                "auth_locked": False,
                "instruments": [],
                "voices": [],
                "choirjobs": [],
                "roles": [],
            },
            headers=headers,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["surname"] == surname.upper()
        assert created["givenname"] == "Max"
        assert created["deletable"] is True

        search_response = client.get(
            "/users/search", params={"q": surname}, headers=headers
        )
        assert created["id"] in [item["id"] for item in search_response.json()]

        show_response = client.get(f"/users/{created['id']}", headers=headers)
        assert show_response.status_code == 200
        assert show_response.json()["surname"] == surname.upper()

        update_response = client.put(
            f"/users/{created['id']}",
            json={
                "givenname": "max",
                "surname": surname,
                "email": None,
                "phone": "+43 660 1234567",
                "auth_locked": True,
                "instruments": [],
                "voices": [],
                "choirjobs": [],
                "roles": [],
            },
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["phone"] == "+43 660 1234567"
        assert update_response.json()["auth_locked"] is True

        delete_response = client.delete(f"/users/{created['id']}", headers=headers)
        assert delete_response.status_code == 200

        final_show = client.get(f"/users/{created['id']}", headers=headers)
        assert final_show.status_code == 404

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.put(
            "/users/999999",
            json={
                "givenname": "Max",
                "surname": _unique(),
                "email": None,
                "phone": None,
                "auth_locked": False,
                "instruments": [],
                "voices": [],
                "choirjobs": [],
                "roles": [],
            },
            headers=headers,
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete("/users/999999", headers=headers)
        assert response.status_code == 404

    def test_form_options_lists_choirjobs(self, client, make_user, db_session):
        choirjob = _make_choirjob(db_session)
        headers = _auth_headers(client, make_user)
        response = client.get("/users/form-options", headers=headers)
        assert response.status_code == 200
        assert choirjob.id in [item["id"] for item in response.json()["choirjobs"]]


class TestQuirks:
    def test_duplicate_name_combo_returns_422_on_both_fields(self, client, make_user):
        headers = _auth_headers(client, make_user)
        surname, givenname = _unique("Doppel"), "Gustav"
        payload = {
            "givenname": givenname,
            "surname": surname,
            "email": None,
            "phone": None,
            "auth_locked": False,
            "instruments": [],
            "voices": [],
            "choirjobs": [],
            "roles": [],
        }
        client.post("/users", json=payload, headers=headers)
        response = client.post("/users", json=payload, headers=headers)
        assert response.status_code == 422
        fields = {error["loc"][1] for error in response.json()["detail"]}
        assert fields == {"surname", "givenname"}

    def test_administrator_target_cannot_be_updated(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        target_admin = make_user(administrator=True)
        response = client.put(
            f"/users/{target_admin.id}",
            json={
                "givenname": target_admin.givenname,
                "surname": target_admin.surname,
                "email": None,
                "phone": None,
                "auth_locked": False,
                "instruments": [],
                "voices": [],
                "choirjobs": [],
                "roles": [],
            },
            headers=headers,
        )
        assert response.status_code == 422

    def test_administrator_target_cannot_be_deleted(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        target_admin = make_user(administrator=True)
        response = client.delete(f"/users/{target_admin.id}", headers=headers)
        assert response.status_code == 422

    def test_user_with_assigned_role_cannot_be_deleted(self, client, make_user):
        headers = _auth_headers(client, make_user)
        target = make_user(roles=["disponent"])
        response = client.delete(f"/users/{target.id}", headers=headers)
        assert response.status_code == 422

    def test_extra_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/users",
            json={
                "givenname": "Max",
                "surname": _unique(),
                "email": None,
                "phone": None,
                "auth_locked": False,
                "instruments": [],
                "voices": [],
                "choirjobs": [],
                "roles": [],
                "administrator": False,
                "bogus_field": True,
            },
            headers=headers,
        )
        assert response.status_code == 422


def _create_user_matching(client, headers, marker: str) -> None:
    client.post(
        "/users",
        json={
            "givenname": "Given",
            "surname": f"{marker}-{uuid.uuid4().hex[:6]}",
            "email": None,
            "phone": None,
            "auth_locked": False,
            "instruments": [],
            "voices": [],
            "choirjobs": [],
            "roles": [],
        },
        headers=headers,
    )


class TestNPlusOne:
    def test_search_query_count_does_not_scale_with_result_count(
        self, client, make_user, count_queries
    ):
        """Regression guard for N+1 in search_users(): the search result is
        a flat id+label projection (no per-row position/role/oauth2 detail
        attached), so the query count must stay the same regardless of how
        many rows come back."""
        headers = _auth_headers(client, make_user)
        marker = _unique("Vielzahl")

        _create_user_matching(client, headers, marker)
        with count_queries() as small:
            small_response = client.get(
                "/users/search", params={"q": marker}, headers=headers
            )

        for _ in range(5):
            _create_user_matching(client, headers, marker)
        with count_queries() as large:
            large_response = client.get(
                "/users/search", params={"q": marker}, headers=headers
            )

        assert small_response.status_code == 200
        assert large_response.status_code == 200
        assert len(large_response.json()) > len(small_response.json())
        assert large.count == small.count


class TestRequestsAndBookings:
    def test_returns_404_for_unknown_user(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/users/999999/requests-and-bookings", headers=headers)
        assert response.status_code == 404

    def test_includes_past_performances_unlike_the_selfadmin_endpoint(
        self, client, make_user, db_session
    ):
        # Legacy's System::UserController::requestsAndBookings() calls the
        # bare `$user->requestsAndBookings()` ($upcomingOnly defaults to
        # false), unlike /support/requests-and-bookings, which stays
        # upcoming-only.
        headers = _auth_headers(client, make_user)
        target = make_user()
        performance = _make_past_performance(db_session)
        now = datetime.now(UTC)
        db_session.add(
            Booking(
                performance_id=performance.id,
                user_id=target.id,
                position_type="instruments",
                position_id=1,
                fee=80,
                order=0,
                created_at=now,
                updated_at=now,
            )
        )
        db_session.commit()

        response = client.get(
            f"/users/{target.id}/requests-and-bookings", headers=headers
        )

        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [performance.id]
