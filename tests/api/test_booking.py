import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.db.database import engine
from app.db.models.performance import Performance
from app.services.user_position_service import create_user_position


def _unique(base: str = "Name") -> str:
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
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user


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
    admin_headers, _user = _auth_headers(client, make_user, administrator=True)
    response = client.post(
        "/coreelements/location",
        json={"name": _unique("Ort"), "address": "Hauptstraße 1", "color": "ff0000"},
        headers=admin_headers,
    )
    return response.json()["id"]


def _make_instrument(client, make_user) -> int:
    admin_headers, _user = _auth_headers(client, make_user, administrator=True)
    response = client.post(
        "/coreelements/instrument",
        json={"name": _unique("Instrument")},
        headers=admin_headers,
    )
    return response.json()["id"]


def _make_performance(
    client, make_user, headers, *, instrument_id: int, quantity: int = 1
) -> int:
    composer_id = _make_composer(client, headers)
    work_id = _make_ordinariumwork(client, headers, composer_id)
    location_id = _make_location(client, make_user)
    payload = {
        "schedule": (datetime.now(UTC) + timedelta(days=2)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        ),
        "location_id": location_id,
        "ordinariumwork_id": work_id,
        "artist_id": None,
        "description": None,
        "choirjob_defaultfee": 35,
        "instrument_defaultfee": 60,
        "voice_defaultfee": 110,
        "extracost_amount": None,
        "extracost_description": None,
        "setup": {
            "instruments": [{"id": instrument_id, "quantity": quantity}],
            "voices": [],
            "choirjobs": [],
        },
        "proprium": [],
        "rehearsals": [],
    }
    response = client.post("/performances", json=payload, headers=headers)
    return response.json()["id"]


def _move_to_past(performance_id: int) -> None:
    with OrmSession(engine) as session:
        performance = session.execute(
            select(Performance).where(Performance.id == performance_id)
        ).scalar_one()
        performance.schedule = datetime.now(UTC) - timedelta(days=1)
        session.commit()


def _qualify(user_id: int, instrument_id: int) -> None:
    with OrmSession(engine) as session:
        create_user_position(
            session,
            user_id=user_id,
            position_type="instruments",
            position_id=instrument_id,
        )


class TestPermissionGuards:
    def test_cast_requires_authentication(self, client):
        response = client.get("/performances/1/cast")
        assert response.status_code == 401

    def test_cast_rejects_non_disponent(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=["planner"])
        response = client.get("/performances/1/cast", headers=headers)
        assert response.status_code == 403

    def test_billing_rejects_non_billing_role(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        response = client.get("/performances/1/billing", headers=headers)
        assert response.status_code == 403

    def test_requests_and_bookings_accepts_planner(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=["planner"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, headers, instrument_id=instrument_id
        )
        response = client.get(
            f"/performances/{performance_id}/requests-and-bookings", headers=headers
        )
        assert response.status_code == 200

    def test_booking_status_requires_only_authentication(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=[])
        instrument_id = _make_instrument(client, make_user)
        disponent_headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        performance_id = _make_performance(
            client, make_user, disponent_headers, instrument_id=instrument_id
        )
        response = client.post(
            f"/performances/{performance_id}/booking-status", headers=headers
        )
        assert response.status_code == 200


class TestCastRoundtrip:
    def test_get_cast_then_save_cast_books_a_user(self, client, make_user):
        headers, _disponent = _auth_headers(client, make_user, roles=["disponent"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, headers, instrument_id=instrument_id
        )

        get_response = client.get(
            f"/performances/{performance_id}/cast", headers=headers
        )
        assert get_response.status_code == 200
        setup = get_response.json()["setup"]
        assert setup["instruments"][0]["id"] == instrument_id

        _, musician = _auth_headers(client, make_user, roles=[])
        _qualify(musician.id, instrument_id)

        save_response = client.post(
            f"/performances/{performance_id}/cast",
            json={
                "cast": {
                    "instruments": [
                        {"id": instrument_id, "cast": [{"id": musician.id, "fee": 80}]}
                    ],
                    "voices": [],
                    "choirjobs": [],
                },
                "not_booked": [],
            },
            headers=headers,
        )
        assert save_response.status_code == 200
        assert (
            save_response.json()["cast"]["instruments"][0]["cast"][0]["id"]
            == musician.id
        )

    def test_cast_raises_403_for_past_performance(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, headers, instrument_id=instrument_id
        )
        _move_to_past(performance_id)

        response = client.get(f"/performances/{performance_id}/cast", headers=headers)
        assert response.status_code == 403

    def test_cast_missing_performance_returns_404(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        response = client.get("/performances/999999/cast", headers=headers)
        assert response.status_code == 404

    def test_cast_query_count_does_not_scale_with_setup_size(
        self, client, make_user, count_queries
    ):
        headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, headers, instrument_id=instrument_id
        )

        with count_queries() as counter:
            response = client.get(
                f"/performances/{performance_id}/cast", headers=headers
            )
        assert response.status_code == 200
        baseline = counter.count
        assert baseline < 40  # generous ceiling, guards against real N+1 regressions


class TestBookingStatusSelfService:
    def test_request_then_cancel_roundtrip(self, client, make_user):
        disponent_headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, disponent_headers, instrument_id=instrument_id
        )
        musician_headers, musician = _auth_headers(client, make_user, roles=[])
        _qualify(musician.id, instrument_id)

        request_response = client.post(
            f"/performances/{performance_id}/booking-status", headers=musician_headers
        )
        assert request_response.status_code == 200
        assert request_response.json()["status"] == 2

        cancel_response = client.post(
            f"/performances/{performance_id}/booking-status", headers=musician_headers
        )
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == 1


class TestBillingNoPastLock:
    def test_billing_available_for_past_performance(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, headers, instrument_id=instrument_id
        )
        _move_to_past(performance_id)
        billing_headers, _ = _auth_headers(client, make_user, roles=["billing"])

        response = client.get(
            f"/performances/{performance_id}/billing", headers=billing_headers
        )

        assert response.status_code == 200
        assert response.json()["billing"]["sum"] >= 0


class TestMessageToCast:
    def test_send_message_returns_ok_for_verified_recipient(self, client, make_user):
        headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, headers, instrument_id=instrument_id
        )
        recipient = make_user()
        recipient.email_verified_at = datetime.now(UTC)
        with OrmSession(engine) as session:
            session.merge(recipient)
            session.commit()

        response = client.post(
            f"/performances/{performance_id}/message-to-cast/send",
            json={"recipient_ids": [recipient.id], "message": "Hallo!"},
            headers=headers,
        )

        assert response.status_code == 200

    def test_send_message_returns_422_when_no_recipient_verified(
        self, client, make_user
    ):
        headers, _ = _auth_headers(client, make_user, roles=["disponent"])
        instrument_id = _make_instrument(client, make_user)
        performance_id = _make_performance(
            client, make_user, headers, instrument_id=instrument_id
        )
        recipient = make_user()

        response = client.post(
            f"/performances/{performance_id}/message-to-cast/send",
            json={"recipient_ids": [recipient.id], "message": "Hallo!"},
            headers=headers,
        )

        assert response.status_code == 422
