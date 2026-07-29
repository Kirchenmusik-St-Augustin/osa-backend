import uuid

import pytest
from sqlalchemy.orm import Session

from app.schemas.artist import ArtistRequest
from app.schemas.propriumwork import PropriumworkRequest
from app.services import artist_service, propriumwork_service


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_artist(db_session: Session) -> int:
    artist = artist_service.create_artist(
        db_session,
        ArtistRequest(
            surname=_unique("Composer"), givenname=_unique("First"), composer=True
        ),
    )
    return artist.id


def _request(
    artist_id: int, name: str | None = None, **overrides: object
) -> PropriumworkRequest:
    defaults: dict[str, object] = {
        "name": name or _unique("Werk"),
        "description": None,
        "artist_id": artist_id,
        "duration": None,
        "demanding": False,
    }
    defaults.update(overrides)
    return PropriumworkRequest(**defaults)  # type: ignore[arg-type]


class TestSearchPropriumworks:
    def test_empty_query_returns_empty(self, db_session: Session):
        assert propriumwork_service.search_propriumworks(db_session, "") == []

    def test_matches_by_work_name(self, db_session: Session):
        artist_id = _make_artist(db_session)
        marker = _unique("Introitus")
        propriumwork_service.create_propriumwork(
            db_session, _request(artist_id, name=marker)
        )

        results = propriumwork_service.search_propriumworks(db_session, marker.lower())

        assert len(results) == 1
        assert marker in results[0].label


class TestCreatePropriumwork:
    def test_basic_create_returns_response_with_artist_name(self, db_session: Session):
        artist = artist_service.create_artist(
            db_session,
            ArtistRequest(surname="Haydn", givenname="Joseph", composer=True),
        )

        response = propriumwork_service.create_propriumwork(
            db_session, _request(artist.id, name=_unique("Graduale"))
        )

        assert response.artist_id == artist.id
        assert response.artist_name == "HAYDN, Joseph"

    def test_rejects_short_name(self, db_session: Session):
        artist_id = _make_artist(db_session)
        with pytest.raises(
            propriumwork_service.PropriumworkValidationError
        ) as exc_info:
            propriumwork_service.create_propriumwork(
                db_session, _request(artist_id, name="ab")
            )

        assert exc_info.value.errors == [
            ("name", "Muss zwischen 3 und 60 Zeichen lang sein.")
        ]

    def test_rejects_unknown_artist(self, db_session: Session):
        with pytest.raises(
            propriumwork_service.PropriumworkValidationError
        ) as exc_info:
            propriumwork_service.create_propriumwork(
                db_session, _request(artist_id=999999)
            )

        assert exc_info.value.errors == [
            ("artist_id", "Komponist/in wurde nicht gefunden.")
        ]

    def test_rejects_duplicate_name_for_same_artist(self, db_session: Session):
        artist_id = _make_artist(db_session)
        name = _unique("Offertorium")
        propriumwork_service.create_propriumwork(
            db_session, _request(artist_id, name=name)
        )

        with pytest.raises(propriumwork_service.PropriumworkValidationError):
            propriumwork_service.create_propriumwork(
                db_session, _request(artist_id, name=name)
            )

    def test_rejects_out_of_range_duration(self, db_session: Session):
        artist_id = _make_artist(db_session)
        with pytest.raises(
            propriumwork_service.PropriumworkValidationError
        ) as exc_info:
            propriumwork_service.create_propriumwork(
                db_session, _request(artist_id, duration=1000)
            )

        assert exc_info.value.errors == [
            ("duration", "Muss zwischen 1 und 999 liegen.")
        ]

    def test_rejects_zero_duration(self, db_session: Session):
        """Legacy quirk: unlike Ordinariumwork, Propriumwork's duration
        lower bound is 1, not 0 -- a duration of exactly 0 is invalid."""
        artist_id = _make_artist(db_session)
        with pytest.raises(
            propriumwork_service.PropriumworkValidationError
        ) as exc_info:
            propriumwork_service.create_propriumwork(
                db_session, _request(artist_id, duration=0)
            )

        assert exc_info.value.errors == [
            ("duration", "Muss zwischen 1 und 999 liegen.")
        ]


class TestUpdatePropriumwork:
    def test_not_found_raises(self, db_session: Session):
        artist_id = _make_artist(db_session)
        with pytest.raises(propriumwork_service.PropriumworkNotFoundError):
            propriumwork_service.update_propriumwork(
                db_session, 999, _request(artist_id)
            )

    def test_keeping_own_name_does_not_trigger_uniqueness_error(
        self, db_session: Session
    ):
        artist_id = _make_artist(db_session)
        name = _unique("Communio")
        created = propriumwork_service.create_propriumwork(
            db_session, _request(artist_id, name=name)
        )

        updated = propriumwork_service.update_propriumwork(
            db_session, created.id, _request(artist_id, name=name, description="neu")
        )

        assert updated.description == "neu"

    def test_duplicate_against_other_row_is_rejected(self, db_session: Session):
        artist_id = _make_artist(db_session)
        name = _unique("Alleluja")
        propriumwork_service.create_propriumwork(
            db_session, _request(artist_id, name=name)
        )
        other = propriumwork_service.create_propriumwork(
            db_session, _request(artist_id)
        )

        with pytest.raises(propriumwork_service.PropriumworkValidationError):
            propriumwork_service.update_propriumwork(
                db_session, other.id, _request(artist_id, name=name)
            )


class TestDeletePropriumwork:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(propriumwork_service.PropriumworkNotFoundError):
            propriumwork_service.delete_propriumwork(db_session, 999)

    def test_succeeds(self, db_session: Session):
        artist_id = _make_artist(db_session)
        created = propriumwork_service.create_propriumwork(
            db_session, _request(artist_id)
        )

        propriumwork_service.delete_propriumwork(db_session, created.id)

        with pytest.raises(propriumwork_service.PropriumworkNotFoundError):
            propriumwork_service.get_propriumwork(db_session, created.id)
