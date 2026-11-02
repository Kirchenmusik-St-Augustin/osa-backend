import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from app.schemas.booking import SendMessageRequest
from app.services import cast_service, message_service
from tests.booking_helpers import (
    create_booking,
    create_choirjob,
    create_instrument,
    create_performance,
    create_voice,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TestSendMessageRequestSchema:
    def test_rejects_oversized_message(self):
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(max_length=2000)
            SendMessageRequest(recipient_ids=[uuid.uuid4()], message="x" * 2001)


class TestGetMessageToCastPage:
    def test_returns_booked_cast_and_own_status(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        booked = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(booked.id, 80)],
            old_quantity=None,
        )
        current_user = make_user()

        page = message_service.get_message_to_cast_page(
            db_session, performance_id, current_user
        )

        assert page.booked_cast.instruments[0].cast[0].id == booked.id
        assert page.user_booking.status == 0  # current_user has no qualification at all


class TestMessageToCast:
    def test_get_message_recipients_type_all_collects_every_booked_user(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        user = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )

        recipients = message_service.get_message_recipients(
            db_session, performance_id, None, None
        )

        assert [r.id for r in recipients] == [user.id]

    def test_get_message_recipients_type_all_preserves_category_order(
        self, db_session: Session, make_user
    ):
        """'alle' recipients are ordered by instruments -> voices ->
        choirjobs, each item's cast in booking order -- not by an unordered
        DB round-trip."""
        instrument = create_instrument(db_session)
        voice = create_voice(db_session)
        choirjob = create_choirjob(db_session)
        performance_id = create_performance(
            db_session,
            instruments={instrument.id: 2},
            voices={voice.id: 1},
            choirjobs={choirjob.id: 1},
        )
        # Created/booked deliberately out of expected order, so a naive
        # unordered fetch would very likely surface the mismatch instead of
        # accidentally matching by luck.
        choirjob_user = make_user()
        voice_user = make_user()
        instrument_user_second = make_user()
        instrument_user_first = make_user()

        cast_service.save_cast_item(
            db_session,
            performance_id,
            "choirjobs",
            choirjob.id,
            new_cast=[(choirjob_user.id, 35)],
            old_quantity=None,
        )
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "voices",
            voice.id,
            new_cast=[(voice_user.id, 110)],
            old_quantity=None,
        )
        # order within the instrument item comes from Booking.order, which
        # is the new_cast list index.
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[
                (instrument_user_first.id, 60),
                (instrument_user_second.id, 60),
            ],
            old_quantity=None,
        )

        recipients = message_service.get_message_recipients(
            db_session, performance_id, None, None
        )

        assert [r.id for r in recipients] == [
            instrument_user_first.id,
            instrument_user_second.id,
            voice_user.id,
            choirjob_user.id,
        ]

    def test_get_message_recipients_for_specific_position(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        voice = create_voice(db_session)
        performance_id = create_performance(
            db_session, instruments={instrument.id: 1}, voices={voice.id: 1}
        )
        instrument_user, voice_user = make_user(), make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(instrument_user.id, 80)],
            old_quantity=None,
        )
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "voices",
            voice.id,
            new_cast=[(voice_user.id, 100)],
            old_quantity=None,
        )

        recipients = message_service.get_message_recipients(
            db_session, performance_id, "voices", voice.id
        )

        assert [r.id for r in recipients] == [voice_user.id]

    def test_get_message_recipients_for_specific_position_preserves_booking_order(
        self, db_session: Session, make_user
    ):
        voice = create_voice(db_session)
        performance_id = create_performance(db_session, voices={voice.id: 2})
        first_user, second_user = make_user(), make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "voices",
            voice.id,
            new_cast=[(first_user.id, 100), (second_user.id, 100)],
            old_quantity=None,
        )

        recipients = message_service.get_message_recipients(
            db_session, performance_id, "voices", voice.id
        )

        assert [r.id for r in recipients] == [first_user.id, second_user.id]

    def test_get_message_recipients_has_email_reflects_verification_status(
        self, db_session: Session, make_user
    ):
        """`has_email` means the email is VERIFIED, not merely "has any
        email address" -- so a recipient whose switch is enabled in the
        MessageToCast UI is always someone who can actually receive the
        message (matches send_message_to_cast()'s own verified-only filter
        one-to-one, instead of letting an unverified address look
        selectable while silently going nowhere)."""
        unverified_instrument = create_instrument(db_session)
        unverified_performance_id = create_performance(
            db_session, instruments={unverified_instrument.id: 1}
        )
        unverified_user = make_user(verified=False)
        cast_service.save_cast_item(
            db_session,
            unverified_performance_id,
            "instruments",
            unverified_instrument.id,
            new_cast=[(unverified_user.id, 80)],
            old_quantity=None,
        )

        verified_instrument = create_instrument(db_session)
        verified_performance_id = create_performance(
            db_session, instruments={verified_instrument.id: 1}
        )
        verified_user = make_user()
        verified_user.email_verified_at = datetime.now(UTC)
        db_session.commit()
        cast_service.save_cast_item(
            db_session,
            verified_performance_id,
            "instruments",
            verified_instrument.id,
            new_cast=[(verified_user.id, 80)],
            old_quantity=None,
        )

        unverified_recipients = message_service.get_message_recipients(
            db_session, unverified_performance_id, None, None
        )
        assert unverified_recipients[0].has_email is False
        assert unverified_recipients[0].email is None

        verified_recipients = message_service.get_message_recipients(
            db_session, verified_performance_id, None, None
        )
        assert verified_recipients[0].has_email is True
        assert verified_recipients[0].email == verified_user.email

    def test_send_message_to_cast_returns_verified_recipients_only(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        sender = make_user()
        recipient = make_user()
        recipient.email_verified_at = datetime.now(UTC)
        db_session.commit()
        create_booking(
            db_session, performance_id, recipient.id, "instruments", instrument.id
        )

        to_emails, sender_name, message = message_service.send_message_to_cast(
            db_session,
            performance_id,
            sender,
            SendMessageRequest(recipient_ids=[recipient.id], message="Hallo!"),
        )

        assert to_emails == [recipient.email]
        assert sender_name == f"{sender.surname}, {sender.givenname}"
        assert message == "Hallo!"

    def test_send_message_to_cast_raises_when_no_recipient_is_verified(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        sender = make_user()
        recipient = make_user(verified=False)
        create_booking(
            db_session, performance_id, recipient.id, "instruments", instrument.id
        )

        with pytest.raises(message_service.MessageRecipientsEmptyError):
            message_service.send_message_to_cast(
                db_session,
                performance_id,
                sender,
                SendMessageRequest(recipient_ids=[recipient.id], message="Hallo!"),
            )

    def test_send_message_to_cast_ignores_users_who_are_not_booked(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        sender = make_user()
        cast_member = make_user()
        outsider = make_user()
        for user in (cast_member, outsider):
            user.email_verified_at = datetime.now(UTC)
        db_session.commit()
        create_booking(
            db_session, performance_id, cast_member.id, "instruments", instrument.id
        )

        to_emails, _sender_name, _message = message_service.send_message_to_cast(
            db_session,
            performance_id,
            sender,
            SendMessageRequest(
                recipient_ids=[cast_member.id, outsider.id], message="Hallo!"
            ),
        )

        assert to_emails == [cast_member.email]

    def test_send_message_to_cast_raises_when_every_recipient_is_an_outsider(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        sender = make_user()
        outsider = make_user()
        outsider.email_verified_at = datetime.now(UTC)
        db_session.commit()

        with pytest.raises(message_service.MessageRecipientsEmptyError):
            message_service.send_message_to_cast(
                db_session,
                performance_id,
                sender,
                SendMessageRequest(recipient_ids=[outsider.id], message="Hallo!"),
            )

    def test_send_message_to_cast_skips_a_booked_user_who_was_deleted(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        sender = make_user()
        deleted_member = make_user()
        deleted_member.email_verified_at = datetime.now(UTC)
        deleted_member.deleted_at = datetime.now(UTC)
        db_session.commit()
        create_booking(
            db_session, performance_id, deleted_member.id, "instruments", instrument.id
        )

        with pytest.raises(message_service.MessageRecipientsEmptyError):
            message_service.send_message_to_cast(
                db_session,
                performance_id,
                sender,
                SendMessageRequest(recipient_ids=[deleted_member.id], message="Hallo!"),
            )
