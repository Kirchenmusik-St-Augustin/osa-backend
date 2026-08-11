import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.datetime_utils import local_now
from app.db.models.location import Location
from app.schemas.artist import ArtistRequest
from app.schemas.ordinariumwork import OrdinariumworkRequest, OrdinariumworkSetupInput
from app.schemas.performance import PerformanceRequest, PerformanceSetupInput
from app.schemas.propriumwork import PropriumworkRequest
from app.services import (
    artist_service,
    ordinariumwork_service,
    performance_service,
    propriumwork_service,
)


def _unique(base: str = "Name") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _request(
    surname: str | None = None,
    givenname: str | None = None,
    **overrides: object,
) -> ArtistRequest:
    defaults: dict[str, object] = {
        "surname": surname or _unique("Surname"),
        "givenname": givenname or _unique("Givenname"),
        "description": None,
        "birthyear": None,
        "deathyear": None,
        "composer": False,
        "conductor": False,
    }
    defaults.update(overrides)
    return ArtistRequest(**defaults)  # type: ignore[arg-type]


class TestListComposerArtists:
    def test_excludes_conductor_only_artists(self, db_session: Session):
        composer = artist_service.create_artist(
            db_session, _request(surname=_unique("Composer"), composer=True)
        )
        artist_service.create_artist(
            db_session,
            _request(surname=_unique("Conductor"), composer=False, conductor=True),
        )

        results = artist_service.list_composer_artists(db_session)

        ids = [artist.id for artist in results]
        assert composer.id in ids
        assert all(artist.composer for artist in results)


class TestSearchArtists:
    def test_empty_query_returns_empty(self, db_session: Session):
        assert artist_service.search_artists(db_session, "") == []

    def test_matches_by_surname_or_givenname(self, db_session: Session):
        marker = _unique("Zzq")
        artist_service.create_artist(
            db_session, _request(surname=marker, givenname="Wolfgang")
        )

        results = artist_service.search_artists(db_session, marker.lower())

        assert [a.surname for a in results] == [marker.upper()]

    def test_all_words_must_match(self, db_session: Session):
        surname, givenname = _unique("Yyr"), _unique("Xxs")
        artist_service.create_artist(
            db_session, _request(surname=surname, givenname=givenname)
        )

        both_words = artist_service.search_artists(
            db_session, f"{surname.lower()} {givenname.lower()}"
        )
        only_surname_plus_bogus = artist_service.search_artists(
            db_session, f"{surname.lower()} nonexistentword"
        )

        assert len(both_words) == 1
        assert only_surname_plus_bogus == []


class TestCreateArtist:
    def test_normalizes_surname_and_givenname(self, db_session: Session):
        artist = artist_service.create_artist(
            db_session, _request(surname="muster", givenname="mary jane")
        )

        assert (artist.surname, artist.givenname) == ("MUSTER", "Mary Jane")

    def test_rejects_short_surname(self, db_session: Session):
        with pytest.raises(artist_service.ArtistValidationError) as exc_info:
            artist_service.create_artist(db_session, _request(surname="ab"))

        assert exc_info.value.errors == [
            ("surname", "Muss zwischen 3 und 32 Zeichen lang sein.")
        ]

    def test_rejects_duplicate_surname_givenname_combination(self, db_session: Session):
        surname, givenname = _unique("Dup"), _unique("Licate")
        artist_service.create_artist(
            db_session, _request(surname=surname, givenname=givenname)
        )

        with pytest.raises(artist_service.ArtistValidationError) as exc_info:
            artist_service.create_artist(
                db_session, _request(surname=surname, givenname=givenname)
            )

        assert exc_info.value.errors == [
            ("surname", "Die Kombination von Vor- und Nachname ist vergeben."),
            ("givenname", "Die Kombination von Vor- und Nachname ist vergeben."),
        ]

    def test_rejects_invalid_birthyear(self, db_session: Session):
        with pytest.raises(artist_service.ArtistValidationError) as exc_info:
            artist_service.create_artist(db_session, _request(birthyear=99))

        assert exc_info.value.errors == [
            ("birthyear", "Muss eine vierstellige Jahreszahl sein.")
        ]

    def test_accepts_plausible_birth_and_death_year(self, db_session: Session):
        artist = artist_service.create_artist(
            db_session, _request(birthyear=1756, deathyear=1791)
        )

        assert (artist.birthyear, artist.deathyear) == (1756, 1791)


class TestUpdateArtist:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(artist_service.ArtistNotFoundError):
            artist_service.update_artist(db_session, 999, _request())

    def test_keeping_own_name_does_not_trigger_uniqueness_error(
        self, db_session: Session
    ):
        surname, givenname = _unique("Same"), _unique("Person")
        artist = artist_service.create_artist(
            db_session, _request(surname=surname, givenname=givenname)
        )

        updated = artist_service.update_artist(
            db_session,
            artist.id,
            _request(surname=surname, givenname=givenname, description="neu"),
        )

        assert updated.description == "neu"

    def test_duplicate_against_other_row_is_rejected(self, db_session: Session):
        surname, givenname = _unique("Taken"), _unique("Combo")
        artist_service.create_artist(
            db_session, _request(surname=surname, givenname=givenname)
        )
        other = artist_service.create_artist(db_session, _request())

        with pytest.raises(artist_service.ArtistValidationError):
            artist_service.update_artist(
                db_session, other.id, _request(surname=surname, givenname=givenname)
            )


class TestDeleteArtist:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(artist_service.ArtistNotFoundError):
            artist_service.delete_artist(db_session, 999)

    def test_succeeds_without_dependents(self, db_session: Session):
        artist = artist_service.create_artist(db_session, _request())

        artist_service.delete_artist(db_session, artist.id)

        with pytest.raises(artist_service.ArtistNotFoundError):
            artist_service.get_artist(db_session, artist.id)

    def test_blocked_when_ordinariumwork_references_artist(self, db_session: Session):
        artist = artist_service.create_artist(db_session, _request(composer=True))
        ordinariumwork_service.create_ordinariumwork(
            db_session,
            OrdinariumworkRequest(
                name=_unique("Werk"),
                artist_id=artist.id,
                setup=OrdinariumworkSetupInput(),
            ),
        )

        with pytest.raises(artist_service.ArtistInUseError):
            artist_service.delete_artist(db_session, artist.id)

    def test_blocked_when_propriumwork_references_artist(self, db_session: Session):
        artist = artist_service.create_artist(db_session, _request(composer=True))
        propriumwork_service.create_propriumwork(
            db_session,
            PropriumworkRequest(name=_unique("Proprium"), artist_id=artist.id),
        )

        with pytest.raises(artist_service.ArtistInUseError):
            artist_service.delete_artist(db_session, artist.id)

    def test_blocked_when_performance_references_artist_as_conductor(
        self, db_session: Session
    ):
        """Retrofit regression guard (Schritt 5): Performance.artist_id is
        the CONDUCTOR, a distinct role from Ordinariumwork/Propriumwork's
        composer artist_id, but both point at the same `artists` table and
        Legacy's own $dependencies treats either role as "in use" alike."""
        composer = artist_service.create_artist(db_session, _request(composer=True))
        conductor = artist_service.create_artist(db_session, _request(conductor=True))
        ordinariumwork = ordinariumwork_service.create_ordinariumwork(
            db_session,
            OrdinariumworkRequest(
                name=_unique("Werk"),
                artist_id=composer.id,
                setup=OrdinariumworkSetupInput(),
            ),
        )
        now = datetime.now(UTC)
        location = Location(
            name=_unique("Location"),
            order=0,
            address="Adresse 1",
            color="000000",
            created_at=now,
            updated_at=now,
        )
        db_session.add(location)
        db_session.commit()
        performance_service.create_performance(
            db_session,
            PerformanceRequest(
                schedule=local_now() + timedelta(days=2),
                location_id=location.id,
                ordinariumwork_id=ordinariumwork.id,
                artist_id=conductor.id,
                description=None,
                choirjob_defaultfee=35,
                instrument_defaultfee=60,
                voice_defaultfee=110,
                extracost_amount=None,
                extracost_description=None,
                setup=PerformanceSetupInput(),
                proprium=[],
                rehearsals=[],
            ),
        )

        with pytest.raises(artist_service.ArtistInUseError):
            artist_service.delete_artist(db_session, conductor.id)
