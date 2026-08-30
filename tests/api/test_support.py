import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.artist import Artist
from app.db.models.booking import Booking
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.user import User


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _auth_headers(
    client, make_user, *, password: str = "correct-password"
) -> tuple[dict[str, str], User]:
    user = make_user(password=password)
    response = client.post(
        "/auth/login", data={"username": user.email, "password": password}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user


def _make_instrument(db_session: Session) -> Instrument:
    now = datetime.now(UTC)
    instrument = Instrument(
        name=_unique("Instrument"), order=0, created_at=now, updated_at=now
    )
    db_session.add(instrument)
    db_session.commit()
    return instrument


def _make_performance(db_session: Session) -> Performance:
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
        # Naive wall-clock, like every real `schedule` write -- NOT
        # datetime.now(UTC) (see app.core.datetime_utils module docstring).
        schedule=datetime(2099, 1, 1, 12, 0, 0),  # noqa: DTZ001
        location_id=location.id,
        ordinariumwork_id=ordinariumwork.id,
        created_at=now,
        updated_at=now,
    )
    db_session.add(performance)
    db_session.commit()
    return performance


class TestPermissionGuard:
    def test_requires_authentication(self, client):
        response = client.get("/support/requests-and-bookings")
        assert response.status_code == 401

    def test_any_authenticated_user_may_call_it(self, client, make_user):
        headers, _user = _auth_headers(client, make_user)
        response = client.get("/support/requests-and-bookings", headers=headers)
        assert response.status_code == 200

    def test_contactpersons_requires_authentication(self, client):
        response = client.get("/support/contactpersons")
        assert response.status_code == 401

    def test_message_to_contactperson_requires_authentication(self, client):
        response = client.post(
            "/support/message-to-contactperson",
            json={"recipient_id": 1, "message": "Hallo!"},
        )
        assert response.status_code == 401


class TestGetMyRequestsAndBookings:
    def test_empty_when_no_bookings_or_requests(self, client, make_user):
        headers, _user = _auth_headers(client, make_user)
        response = client.get("/support/requests-and-bookings", headers=headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_includes_own_booking(self, client, make_user, db_session):
        headers, user = _auth_headers(client, make_user)
        instrument = _make_instrument(db_session)
        performance = _make_performance(db_session)
        now = datetime.now(UTC)
        db_session.add(
            Booking(
                performance_id=performance.id,
                user_id=user.id,
                position_type="instruments",
                position_id=instrument.id,
                fee=80,
                order=0,
                created_at=now,
                updated_at=now,
            )
        )
        db_session.commit()

        response = client.get("/support/requests-and-bookings", headers=headers)
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [performance.id]


class TestGetContactpersons:
    def test_lists_role_with_description_and_contacts(
        self, client, make_user, db_session
    ):
        headers, _caller = _auth_headers(client, make_user)
        role_name = _unique("planner")
        contact = make_user(roles=[role_name])
        role = contact.roles[0]
        role.description = "Plant den Dienstplan."
        db_session.commit()

        response = client.get("/support/contactpersons", headers=headers)
        assert response.status_code == 200
        entry = next(r for r in response.json() if r["id"] == role.id)
        assert entry["description"] == "Plant den Dienstplan."
        assert [u["id"] for u in entry["users"]] == [contact.id]

    def test_query_count_does_not_scale_with_role_or_contact_count(
        self, client, make_user, count_queries
    ):
        headers, _caller = _auth_headers(client, make_user)
        for _ in range(5):
            make_user(roles=[_unique("scores")])

        with count_queries() as counter:
            response = client.get("/support/contactpersons", headers=headers)
        assert response.status_code == 200
        baseline = counter.count

        for _ in range(5):
            make_user(roles=[_unique("billing")])

        with count_queries() as counter:
            response = client.get("/support/contactpersons", headers=headers)
        assert response.status_code == 200
        assert counter.count == baseline


class TestSendMessageToContactperson:
    def test_sends_and_returns_200_for_a_verified_recipient(
        self, client, make_user, db_session, fake_arq_pool
    ):
        headers, _sender = _auth_headers(client, make_user)
        recipient = make_user(email=f"{_unique('kontakt')}@example.test")

        response = client.post(
            "/support/message-to-contactperson",
            json={"recipient_id": recipient.id, "message": "Bitte um Rückruf."},
            headers=headers,
        )

        assert response.status_code == 200
        fake_arq_pool.enqueue_job.assert_called_once()
        args = fake_arq_pool.enqueue_job.call_args.args
        assert args[0] == "send_user_message_email_task"
        assert args[1] == [recipient.email]

    def test_silent_noop_for_unverified_recipient_still_returns_200(
        self, client, make_user, fake_arq_pool
    ):
        # Legacy quirk regression test (see support_service.
        # send_message_to_contactperson's docstring): missing email
        # verification silently drops the send, but the endpoint still
        # answers 200 -- no leak of who's verified vs. not.
        headers, _sender = _auth_headers(client, make_user)
        recipient = make_user(verified=False)

        response = client.post(
            "/support/message-to-contactperson",
            json={"recipient_id": recipient.id, "message": "Bitte um Rückruf."},
            headers=headers,
        )

        assert response.status_code == 200
        fake_arq_pool.enqueue_job.assert_not_called()

    def test_silent_noop_for_nonexistent_recipient_still_returns_200(
        self, client, make_user, fake_arq_pool
    ):
        headers, _sender = _auth_headers(client, make_user)

        response = client.post(
            "/support/message-to-contactperson",
            json={"recipient_id": 0, "message": "Bitte um Rückruf."},
            headers=headers,
        )

        assert response.status_code == 200
        fake_arq_pool.enqueue_job.assert_not_called()

    def test_rejects_message_shorter_than_three_chars(self, client, make_user):
        headers, _sender = _auth_headers(client, make_user)
        response = client.post(
            "/support/message-to-contactperson",
            json={"recipient_id": 1, "message": "Hi"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_rejects_unknown_fields(self, client, make_user):
        headers, _sender = _auth_headers(client, make_user)
        response = client.post(
            "/support/message-to-contactperson",
            json={"recipient_id": 1, "message": "Hallo!", "extra": "nope"},
            headers=headers,
        )
        assert response.status_code == 422
