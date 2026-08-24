import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.performance import Performance


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, roles: list[str] | None = None, administrator: bool = False
) -> dict[str, str]:
    user = make_user(
        password="correct-password",
        roles=roles if roles is not None else ["planner"],
        administrator=administrator,
    )
    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-password"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_composer(client, headers) -> int:
    response = client.post(
        "/artists",
        json={
            "surname": _unique("Composer"),
            "givenname": _unique("First"),
            "description": None,
            "birthyear": None,
            "deathyear": None,
            "composer": True,
            "conductor": False,
        },
        headers=headers,
    )
    return response.json()["id"]


def _make_ordinariumwork(client, headers, composer_id: int) -> int:
    response = client.post(
        "/ordinariumworks",
        json={
            "name": _unique("Werk"),
            "description": None,
            "artist_id": composer_id,
            "duration": None,
            "demanding": False,
            "setup": {"instruments": [], "voices": []},
        },
        headers=headers,
    )
    return response.json()["id"]


def _make_location(client, make_user) -> int:
    admin_headers = _auth_headers(client, make_user, administrator=True)
    response = client.post(
        "/coreelements/location",
        json={"name": _unique("Ort"), "address": "Hauptstraße 1", "color": "ff0000"},
        headers=admin_headers,
    )
    return response.json()["id"]


def _move_to_past(db_session: Session, performance_id: int) -> None:
    """There is no API path to move an existing performance's schedule
    into the past (updates are themselves schedule-validated) -- forcing
    it directly at the DB layer mirrors the equivalent service-level test.

    Uses the test's own db_session (not an independent Session(engine)) so
    the mutation is visible to the SAME session client's requests are
    routed through via conftest.py's override_get_db() -- a separate
    session bound to its own connection would be isolated behind the
    test's still-open outer transaction and never see this row at all."""
    performance = db_session.execute(
        select(Performance).where(Performance.id == performance_id)
    ).scalar_one()
    performance.schedule = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()


def _base_payload(
    location_id: int, ordinariumwork_id: int, **overrides: object
) -> dict:
    payload: dict[str, object] = {
        "schedule": (datetime.now(UTC) + timedelta(days=2)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        "location_id": location_id,
        "ordinariumwork_id": ordinariumwork_id,
        "artist_id": None,
        "description": None,
        "choirjob_defaultfee": 35,
        "instrument_defaultfee": 60,
        "voice_defaultfee": 110,
        "extracost_amount": None,
        "extracost_description": None,
        "setup": {"instruments": [], "voices": [], "choirjobs": []},
        "proprium": [],
        "rehearsals": [],
    }
    payload.update(overrides)
    return payload


class TestPermissionGuard:
    def test_calendar_list_requires_authentication(self, client):
        response = client.get("/performances", params={"year": 2026, "month": 7})
        assert response.status_code == 401

    def test_calendar_list_does_not_require_performance_maintain(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get(
            "/performances", params={"year": 2026, "month": 7}, headers=headers
        )
        assert response.status_code == 200

    def test_create_requires_performance_maintain(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.post(
            "/performances", json=_base_payload(1, 1), headers=headers
        )
        assert response.status_code == 403

    def test_available_requires_performance_maintain(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get("/performances/available", headers=headers)
        assert response.status_code == 403


class TestCrudRoundtrip:
    def test_create_show_update_delete_performance(self, client, make_user):
        headers = _auth_headers(client, make_user)
        composer_id = _make_composer(client, headers)
        work_id = _make_ordinariumwork(client, headers, composer_id)
        location_id = _make_location(client, make_user)

        create_response = client.post(
            "/performances", json=_base_payload(location_id, work_id), headers=headers
        )
        assert create_response.status_code == 201
        created = create_response.json()

        show_response = client.get(f"/performances/{created['id']}", headers=headers)
        assert show_response.status_code == 200
        assert show_response.json()["ordinariumwork_id"] == work_id
        assert show_response.json()["ordinariumwork_artist_name"]

        update_response = client.put(
            f"/performances/{created['id']}",
            json=_base_payload(location_id, work_id, description="Aktualisiert"),
            headers=headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["description"] == "Aktualisiert"

        delete_response = client.delete(
            f"/performances/{created['id']}", headers=headers
        )
        assert delete_response.status_code == 200

        final_show = client.get(f"/performances/{created['id']}", headers=headers)
        assert final_show.status_code == 404

    def test_get_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/performances/999", headers=headers)
        assert response.status_code == 404

    def test_update_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        composer_id = _make_composer(client, headers)
        work_id = _make_ordinariumwork(client, headers, composer_id)
        location_id = _make_location(client, make_user)

        response = client.put(
            "/performances/999",
            json=_base_payload(location_id, work_id),
            headers=headers,
        )
        assert response.status_code == 404

    def test_delete_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.delete("/performances/999", headers=headers)
        assert response.status_code == 404


class TestFormData:
    def test_form_data_missing_id_returns_404(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/performances/999/form", headers=headers)
        assert response.status_code == 404

    def test_form_data_includes_ordinariumwork_label_and_setup(self, client, make_user):
        headers = _auth_headers(client, make_user)
        composer_id = _make_composer(client, headers)
        work_id = _make_ordinariumwork(client, headers, composer_id)
        location_id = _make_location(client, make_user)
        create_response = client.post(
            "/performances", json=_base_payload(location_id, work_id), headers=headers
        )
        performance_id = create_response.json()["id"]

        response = client.get(f"/performances/{performance_id}/form", headers=headers)

        assert response.status_code == 200
        assert response.json()["location_id"] == location_id
        assert response.json()["deletable"] is True


class TestPastLock:
    def test_update_past_performance_returns_403(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user)
        composer_id = _make_composer(client, headers)
        work_id = _make_ordinariumwork(client, headers, composer_id)
        location_id = _make_location(client, make_user)
        create_response = client.post(
            "/performances", json=_base_payload(location_id, work_id), headers=headers
        )
        performance_id = create_response.json()["id"]

        _move_to_past(db_session, performance_id)

        response = client.put(
            f"/performances/{performance_id}",
            json=_base_payload(location_id, work_id),
            headers=headers,
        )
        assert response.status_code == 403

        delete_response = client.delete(
            f"/performances/{performance_id}", headers=headers
        )
        assert delete_response.status_code == 403

        form_response = client.get(
            f"/performances/{performance_id}/form", headers=headers
        )
        assert form_response.status_code == 403


class TestValidation:
    def test_schedule_before_tomorrow_returns_422(self, client, make_user):
        headers = _auth_headers(client, make_user)
        composer_id = _make_composer(client, headers)
        work_id = _make_ordinariumwork(client, headers, composer_id)
        location_id = _make_location(client, make_user)

        payload = _base_payload(
            location_id,
            work_id,
            schedule=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        )
        response = client.post("/performances", json=payload, headers=headers)

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "schedule"]

    def test_extra_body_field_is_rejected(self, client, make_user):
        headers = _auth_headers(client, make_user)
        composer_id = _make_composer(client, headers)
        work_id = _make_ordinariumwork(client, headers, composer_id)
        location_id = _make_location(client, make_user)

        payload = _base_payload(location_id, work_id, unknown_field="x")
        response = client.post("/performances", json=payload, headers=headers)

        assert response.status_code == 422


class TestQueryCount:
    def test_calendar_list_query_count_does_not_scale_with_row_count(
        self, client, make_user, count_queries
    ):
        """Regression guard for N+1 in list_performances_for_month(): the
        query count must stay flat as more performances are added to the
        same month."""
        headers = _auth_headers(client, make_user)
        composer_id = _make_composer(client, headers)
        work_id = _make_ordinariumwork(client, headers, composer_id)
        location_id = _make_location(client, make_user)

        year, month = 2033, 3
        schedule = datetime(year, month, 5, 11, 0, tzinfo=UTC)
        client.post(
            "/performances",
            json=_base_payload(
                location_id, work_id, schedule=schedule.strftime("%Y-%m-%dT%H:%M:%S")
            ),
            headers=headers,
        )
        with count_queries() as small:
            small_response = client.get(
                "/performances", params={"year": year, "month": month}, headers=headers
            )

        for day in range(6, 11):
            client.post(
                "/performances",
                json=_base_payload(
                    location_id,
                    work_id,
                    schedule=schedule.replace(day=day).strftime("%Y-%m-%dT%H:%M:%S"),
                ),
                headers=headers,
            )
        with count_queries() as large:
            large_response = client.get(
                "/performances", params={"year": year, "month": month}, headers=headers
            )

        assert small_response.status_code == 200
        assert large_response.status_code == 200
        assert len(large_response.json()) > len(small_response.json())
        assert large.count == small.count
        assert "user_booking" in small_response.json()[0]
        assert small_response.json()[0]["user_booking"]["status"] in range(6)
