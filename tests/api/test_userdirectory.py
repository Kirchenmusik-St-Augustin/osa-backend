import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.choirjob import Choirjob
from app.services import user_position_service


def _unique(base: str = "Directory") -> str:
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


class TestPermissionGuard:
    def test_list_requires_authentication(self, client):
        response = client.get("/userdirectory")
        assert response.status_code == 401

    def test_list_rejects_user_without_disponent_role_or_administrator(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, roles=[])
        response = client.get("/userdirectory", headers=headers)
        assert response.status_code == 403

    def test_abilities_allows_disponent(self, client, make_user):
        headers = _auth_headers(client, make_user, roles=["disponent"])
        response = client.get("/userdirectory/abilities", headers=headers)
        assert response.status_code == 200


class TestListUsers:
    def test_no_type_defaults_to_all(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/userdirectory", headers=headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_email_hidden_until_verified(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user)
        marker = _unique("Unverified")
        user = make_user(email=f"{marker.lower()}@example.com", verified=False)
        user.surname = marker
        db_session.commit()

        response = client.get("/userdirectory", params={"type": "all"}, headers=headers)
        entry = next(item for item in response.json() if item["id"] == user.id)
        assert entry["has_email"] is False
        assert entry["email"] is None

    def test_email_shown_once_verified(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user)
        marker = _unique("Verified")
        user = make_user(email=f"{marker.lower()}@example.com")
        user.surname = marker
        user.email_verified_at = datetime.now(UTC)
        db_session.commit()

        response = client.get("/userdirectory", params={"type": "all"}, headers=headers)
        entry = next(item for item in response.json() if item["id"] == user.id)
        assert entry["has_email"] is True
        assert entry["email"] == user.email

    def test_filters_by_position_type_and_id(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user)
        choirjob = _make_choirjob(db_session)
        marker = _unique("Substitut")
        matching = make_user()
        matching.surname = marker
        db_session.commit()

        user_position_service.create_user_position(
            db_session,
            user_id=matching.id,
            position_type="choirjobs",
            position_id=choirjob.id,
        )

        response = client.get(
            "/userdirectory",
            params={"type": "choirjobs", "id": choirjob.id},
            headers=headers,
        )
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()]
        assert ids == [matching.id]

    def test_type_without_id_returns_empty(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get(
            "/userdirectory", params={"type": "instruments"}, headers=headers
        )
        assert response.status_code == 200
        assert response.json() == []


class TestAbilities:
    def test_lists_choirjob_catalog(self, client, make_user, db_session):
        headers = _auth_headers(client, make_user)
        choirjob = _make_choirjob(db_session)

        response = client.get("/userdirectory/abilities", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert "roles" not in body
        assert choirjob.id in [item["id"] for item in body["choirjobs"]]
