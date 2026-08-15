"""Regression tests for scripts/backfill_choir_voice_tags.py."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.booking import Booking
from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.user import User
from app.db.models.user_position import UserPosition
from app.db.models.voice import Voice
from scripts import backfill_choir_voice_tags


def _unique(base: str) -> str:
    # `name` is UNIQUE on Choirjob/Instrument/Voice, and this test DB is
    # shared across the whole run (not reset per test) -- same established
    # pattern as test_booking_service.py's own _unique() helper.
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_choirjob(db_session: Session, *, order: int = 0) -> Choirjob:
    now = datetime.now(UTC)
    choirjob = Choirjob(
        name=_unique("Chorist"), order=order, created_at=now, updated_at=now
    )
    db_session.add(choirjob)
    db_session.commit()
    return choirjob


def _make_instrument(db_session: Session, *, order: int = 0) -> Instrument:
    now = datetime.now(UTC)
    instrument = Instrument(
        name=_unique("Violine"), order=order, created_at=now, updated_at=now
    )
    db_session.add(instrument)
    db_session.commit()
    return instrument


def _get_or_create_voice(db_session: Session, *, name: str) -> Voice:
    # Unlike Choirjob/Instrument above, the script looks these up by their
    # exact canonical German name (TAG_TO_VOICE_NAME) -- can't suffix them
    # unique. The shared test DB persists across tests within a run, so an
    # earlier test may have already created this exact Voice; reuse it
    # instead of colliding with the UNIQUE(name) constraint.
    existing = db_session.execute(
        select(Voice).where(Voice.name == name)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    voice = Voice(name=name, order=0, created_at=now, updated_at=now)
    db_session.add(voice)
    db_session.commit()
    return voice


def _book(
    db_session: Session, user_id: int, position_type: str, position_id: int
) -> Booking:
    now = datetime.now(UTC)
    booking = Booking(
        performance_id=1,
        user_id=user_id,
        position_type=position_type,
        position_id=position_id,
        fee=35,
        order=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(booking)
    db_session.commit()
    return booking


def _voice_ids_for(db_session: Session, user_id: int) -> set[int]:
    return set(
        db_session.execute(
            select(UserPosition.position_id).where(
                UserPosition.user_id == user_id, UserPosition.position_type == "voices"
            )
        )
        .scalars()
        .all()
    )


class TestRunBackfill:
    def test_maps_a_user_with_a_recognized_tag(
        self, db_session: Session, make_user, capsys: pytest.CaptureFixture[str]
    ):
        choirjob = _make_choirjob(db_session)
        sopran = _get_or_create_voice(db_session, name="Sopran")
        user = make_user()
        user.surname = "FUTAEDA (S)"
        db_session.commit()
        _book(db_session, user.id, "choirjobs", choirjob.id)

        backfill_choir_voice_tags.run_backfill(db_session, dry_run=False)

        assert _voice_ids_for(db_session, user.id) == {sopran.id}
        assert "[map]" in capsys.readouterr().out

    def test_skips_a_user_without_any_bracket_tag(
        self, db_session: Session, make_user, capsys: pytest.CaptureFixture[str]
    ):
        choirjob = _make_choirjob(db_session)
        user = make_user()
        user.surname = "OHNEKUERZEL"
        db_session.commit()
        _book(db_session, user.id, "choirjobs", choirjob.id)

        backfill_choir_voice_tags.run_backfill(db_session, dry_run=False)

        assert _voice_ids_for(db_session, user.id) == set()
        assert "kein Klammer-Kürzel im Namen" in capsys.readouterr().out

    def test_skips_an_unrecognized_tag_instead_of_guessing(
        self, db_session: Session, make_user, capsys: pytest.CaptureFixture[str]
    ):
        choirjob = _make_choirjob(db_session)
        _get_or_create_voice(db_session, name="Tenor")
        user = make_user()
        user.surname = "PICHLER (T1)"
        db_session.commit()
        _book(db_session, user.id, "choirjobs", choirjob.id)

        backfill_choir_voice_tags.run_backfill(db_session, dry_run=False)

        assert _voice_ids_for(db_session, user.id) == set()
        assert "unbekanntes Kürzel 'T1'" in capsys.readouterr().out

    def test_reports_already_present_without_creating_a_duplicate(
        self, db_session: Session, make_user, capsys: pytest.CaptureFixture[str]
    ):
        choirjob = _make_choirjob(db_session)
        sopran = _get_or_create_voice(db_session, name="Sopran")
        user = make_user()
        user.surname = "FUTAEDA (S)"
        db_session.commit()
        _book(db_session, user.id, "choirjobs", choirjob.id)
        backfill_choir_voice_tags.run_backfill(db_session, dry_run=False)

        backfill_choir_voice_tags.run_backfill(db_session, dry_run=False)

        assert _voice_ids_for(db_session, user.id) == {sopran.id}
        assert "bereits vorhanden (Sopran)" in capsys.readouterr().out

    def test_dry_run_reports_without_writing(
        self, db_session: Session, make_user, capsys: pytest.CaptureFixture[str]
    ):
        choirjob = _make_choirjob(db_session)
        _get_or_create_voice(db_session, name="Sopran")
        user = make_user()
        user.surname = "FUTAEDA (S)"
        db_session.commit()
        _book(db_session, user.id, "choirjobs", choirjob.id)

        backfill_choir_voice_tags.run_backfill(db_session, dry_run=True)

        assert _voice_ids_for(db_session, user.id) == set()
        out = capsys.readouterr().out
        assert "würde mappen" in out
        assert "-> Sopran" in out

    def test_only_considers_users_booked_into_a_choirjobs_position(
        self, db_session: Session, make_user
    ):
        instrument = _make_instrument(db_session)
        _get_or_create_voice(db_session, name="Sopran")
        user = make_user()
        user.surname = "AUSSENVOR (S)"
        db_session.commit()
        _book(db_session, user.id, "instruments", instrument.id)

        backfill_choir_voice_tags.run_backfill(db_session, dry_run=False)

        assert _voice_ids_for(db_session, user.id) == set()

    def test_never_rewrites_the_surname_itself(self, db_session: Session, make_user):
        choirjob = _make_choirjob(db_session)
        _get_or_create_voice(db_session, name="Sopran")
        user = make_user()
        user.surname = "FUTAEDA (S)"
        db_session.commit()
        _book(db_session, user.id, "choirjobs", choirjob.id)

        backfill_choir_voice_tags.run_backfill(db_session, dry_run=False)

        refreshed = db_session.execute(
            select(User).where(User.id == user.id)
        ).scalar_one()
        assert refreshed.surname == "FUTAEDA (S)"
