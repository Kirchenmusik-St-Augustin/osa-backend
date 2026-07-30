import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.datetime_utils import local_now
from app.db.models.instrument import Instrument
from app.db.models.location import Location
from app.db.models.voice import Voice
from app.schemas.artist import ArtistRequest
from app.schemas.ordinariumwork import (
    OrdinariumworkPositionInput,
    OrdinariumworkRequest,
    OrdinariumworkSetupInput,
)
from app.schemas.performance import PerformanceRequest, PerformanceSetupInput
from app.services import artist_service, ordinariumwork_service, performance_service


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


def _make_instrument(db_session: Session) -> Instrument:
    now = datetime.now(UTC)
    instrument = Instrument(
        name=_unique("Instrument"), order=0, created_at=now, updated_at=now
    )
    db_session.add(instrument)
    db_session.commit()
    return instrument


def _make_voice(db_session: Session) -> Voice:
    now = datetime.now(UTC)
    voice = Voice(name=_unique("Voice"), order=0, created_at=now, updated_at=now)
    db_session.add(voice)
    db_session.commit()
    return voice


def _make_location(db_session: Session) -> Location:
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
    return location


def _make_performance(
    db_session: Session, location_id: int, ordinariumwork_id: int
) -> None:
    performance_service.create_performance(
        db_session,
        PerformanceRequest(
            schedule=local_now() + timedelta(days=2),
            location_id=location_id,
            ordinariumwork_id=ordinariumwork_id,
            artist_id=None,
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


def _request(
    artist_id: int,
    name: str | None = None,
    setup: OrdinariumworkSetupInput | None = None,
    **overrides: object,
) -> OrdinariumworkRequest:
    defaults: dict[str, object] = {
        "name": name or _unique("Werk"),
        "description": None,
        "artist_id": artist_id,
        "duration": None,
        "demanding": False,
        "setup": setup or OrdinariumworkSetupInput(),
    }
    defaults.update(overrides)
    return OrdinariumworkRequest(**defaults)  # type: ignore[arg-type]


class TestGetAvailablePositions:
    def test_returns_instruments_and_voices_ordered_by_core_element_order(
        self, db_session: Session
    ):
        # Shared SQLite test DB has no per-test rollback (see conftest.py) --
        # other tests' Instrument/Voice rows persist across this whole
        # file, so assertions must check relative order/membership, not
        # exact list equality.
        first = _make_instrument(db_session)
        second = _make_instrument(db_session)
        second.order = -1
        db_session.commit()
        voice = _make_voice(db_session)

        result = ordinariumwork_service.get_available_positions(db_session)

        instrument_ids = [item.id for item in result.instruments]
        assert instrument_ids.index(second.id) < instrument_ids.index(first.id)
        assert voice.id in [item.id for item in result.voices]


class TestSearchOrdinariumworks:
    def test_empty_query_returns_empty(self, db_session: Session):
        assert ordinariumwork_service.search_ordinariumworks(db_session, "") == []

    def test_matches_by_work_name(self, db_session: Session):
        artist_id = _make_artist(db_session)
        marker = _unique("Requiem")
        ordinariumwork_service.create_ordinariumwork(
            db_session, _request(artist_id, name=marker)
        )

        results = ordinariumwork_service.search_ordinariumworks(
            db_session, marker.lower()
        )

        assert len(results) == 1
        assert marker in results[0].label


class TestCreateOrdinariumwork:
    def test_basic_create_returns_response_with_artist_name(self, db_session: Session):
        artist = artist_service.create_artist(
            db_session,
            ArtistRequest(surname="Mozart", givenname="Wolfgang", composer=True),
        )

        response = ordinariumwork_service.create_ordinariumwork(
            db_session, _request(artist.id, name=_unique("Krönungsmesse"))
        )

        assert response.artist_id == artist.id
        assert response.artist_name == "MOZART, Wolfgang"

    def test_rejects_short_name(self, db_session: Session):
        artist_id = _make_artist(db_session)
        with pytest.raises(
            ordinariumwork_service.OrdinariumworkValidationError
        ) as exc_info:
            ordinariumwork_service.create_ordinariumwork(
                db_session, _request(artist_id, name="ab")
            )

        assert exc_info.value.errors == [
            ("name", "Muss zwischen 3 und 60 Zeichen lang sein.")
        ]

    def test_rejects_unknown_artist(self, db_session: Session):
        with pytest.raises(
            ordinariumwork_service.OrdinariumworkValidationError
        ) as exc_info:
            ordinariumwork_service.create_ordinariumwork(
                db_session, _request(artist_id=999999)
            )

        assert exc_info.value.errors == [
            ("artist_id", "Komponist/in wurde nicht gefunden.")
        ]

    def test_rejects_duplicate_name_for_same_artist(self, db_session: Session):
        artist_id = _make_artist(db_session)
        name = _unique("Messe")
        ordinariumwork_service.create_ordinariumwork(
            db_session, _request(artist_id, name=name)
        )

        with pytest.raises(ordinariumwork_service.OrdinariumworkValidationError):
            ordinariumwork_service.create_ordinariumwork(
                db_session, _request(artist_id, name=name)
            )

    def test_rejects_unknown_instrument_in_setup(self, db_session: Session):
        artist_id = _make_artist(db_session)
        setup = OrdinariumworkSetupInput(
            instruments=[OrdinariumworkPositionInput(id=999999, quantity=1)]
        )

        with pytest.raises(
            ordinariumwork_service.OrdinariumworkValidationError
        ) as exc_info:
            ordinariumwork_service.create_ordinariumwork(
                db_session, _request(artist_id, setup=setup)
            )

        assert exc_info.value.errors == [
            ("setup", "instruments: Element nicht gefunden.")
        ]

    def test_rejects_duplicate_position_entry(self, db_session: Session):
        artist_id = _make_artist(db_session)
        instrument = _make_instrument(db_session)
        setup = OrdinariumworkSetupInput(
            instruments=[
                OrdinariumworkPositionInput(id=instrument.id, quantity=1),
                OrdinariumworkPositionInput(id=instrument.id, quantity=2),
            ]
        )

        with pytest.raises(
            ordinariumwork_service.OrdinariumworkValidationError
        ) as exc_info:
            ordinariumwork_service.create_ordinariumwork(
                db_session, _request(artist_id, setup=setup)
            )

        assert exc_info.value.errors == [("setup", "instruments: doppelter Eintrag.")]

    def test_persists_setup_positions(self, db_session: Session):
        artist_id = _make_artist(db_session)
        instrument = _make_instrument(db_session)
        voice = _make_voice(db_session)
        setup = OrdinariumworkSetupInput(
            instruments=[OrdinariumworkPositionInput(id=instrument.id, quantity=2)],
            voices=[OrdinariumworkPositionInput(id=voice.id, quantity=4)],
        )

        response = ordinariumwork_service.create_ordinariumwork(
            db_session, _request(artist_id, setup=setup)
        )
        result = ordinariumwork_service.get_setup(db_session, response.id)

        assert [(i.id, i.name, i.quantity) for i in result.instruments] == [
            (instrument.id, instrument.name, 2)
        ]
        assert [(v.id, v.name, v.quantity) for v in result.voices] == [
            (voice.id, voice.name, 4)
        ]


class TestUpdateOrdinariumwork:
    def test_not_found_raises(self, db_session: Session):
        artist_id = _make_artist(db_session)
        with pytest.raises(ordinariumwork_service.OrdinariumworkNotFoundError):
            ordinariumwork_service.update_ordinariumwork(
                db_session, 999, _request(artist_id)
            )

    def test_setup_sync_removes_updates_and_adds_positions(self, db_session: Session):
        artist_id = _make_artist(db_session)
        kept = _make_instrument(db_session)
        removed = _make_instrument(db_session)
        added = _make_voice(db_session)

        created = ordinariumwork_service.create_ordinariumwork(
            db_session,
            _request(
                artist_id,
                setup=OrdinariumworkSetupInput(
                    instruments=[
                        OrdinariumworkPositionInput(id=kept.id, quantity=1),
                        OrdinariumworkPositionInput(id=removed.id, quantity=1),
                    ]
                ),
            ),
        )

        ordinariumwork_service.update_ordinariumwork(
            db_session,
            created.id,
            _request(
                artist_id,
                name=created.name,
                setup=OrdinariumworkSetupInput(
                    instruments=[OrdinariumworkPositionInput(id=kept.id, quantity=9)],
                    voices=[OrdinariumworkPositionInput(id=added.id, quantity=3)],
                ),
            ),
        )

        setup = ordinariumwork_service.get_setup(db_session, created.id)
        assert [(i.id, i.quantity) for i in setup.instruments] == [(kept.id, 9)]
        assert [(v.id, v.quantity) for v in setup.voices] == [(added.id, 3)]


class TestGetSetup:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(ordinariumwork_service.OrdinariumworkNotFoundError):
            ordinariumwork_service.get_setup(db_session, 999)

    def test_empty_setup_returns_empty_lists(self, db_session: Session):
        artist_id = _make_artist(db_session)
        created = ordinariumwork_service.create_ordinariumwork(
            db_session, _request(artist_id)
        )

        setup = ordinariumwork_service.get_setup(db_session, created.id)

        assert (setup.instruments, setup.voices) == ([], [])

    def test_output_order_follows_instrument_order_column_not_insertion_order(
        self, db_session: Session
    ):
        """Regression guard for a real parity bug found via Playwright
        against production data (2026-07-29): Legacy's Instrument/Voice
        models carry a global order-by-`order` scope that applies even to
        the Ordinariumwork setup relation -- the setup table's row order
        must follow each item's own `order` column, not pivot-row insertion
        order or `id`."""
        artist_id = _make_artist(db_session)
        first_added = _make_instrument(db_session)
        first_added.order = 10
        second_added = _make_instrument(db_session)
        second_added.order = 1
        db_session.commit()

        created = ordinariumwork_service.create_ordinariumwork(
            db_session,
            _request(
                artist_id,
                setup=OrdinariumworkSetupInput(
                    instruments=[
                        OrdinariumworkPositionInput(id=first_added.id, quantity=1),
                        OrdinariumworkPositionInput(id=second_added.id, quantity=2),
                    ]
                ),
            ),
        )

        setup = ordinariumwork_service.get_setup(db_session, created.id)

        assert [item.id for item in setup.instruments] == [
            second_added.id,
            first_added.id,
        ]


class TestDeleteOrdinariumwork:
    def test_not_found_raises(self, db_session: Session):
        with pytest.raises(ordinariumwork_service.OrdinariumworkNotFoundError):
            ordinariumwork_service.delete_ordinariumwork(db_session, 999)

    def test_deletes_ordinariumwork_and_its_positions(self, db_session: Session):
        artist_id = _make_artist(db_session)
        instrument = _make_instrument(db_session)
        created = ordinariumwork_service.create_ordinariumwork(
            db_session,
            _request(
                artist_id,
                setup=OrdinariumworkSetupInput(
                    instruments=[
                        OrdinariumworkPositionInput(id=instrument.id, quantity=1)
                    ]
                ),
            ),
        )

        ordinariumwork_service.delete_ordinariumwork(db_session, created.id)

        with pytest.raises(ordinariumwork_service.OrdinariumworkNotFoundError):
            ordinariumwork_service.get_ordinariumwork(db_session, created.id)

    def test_blocked_when_performance_references_it(self, db_session: Session):
        """Retrofit regression guard (Schritt 5): Legacy's only
        HasDependencies target for Ordinariumwork (`performances`) now
        exists in osa-backend."""
        artist_id = _make_artist(db_session)
        location = _make_location(db_session)
        created = ordinariumwork_service.create_ordinariumwork(
            db_session, _request(artist_id)
        )
        _make_performance(db_session, location.id, created.id)

        with pytest.raises(ordinariumwork_service.OrdinariumworkInUseError):
            ordinariumwork_service.delete_ordinariumwork(db_session, created.id)
