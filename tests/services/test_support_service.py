import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models.user_role import UserRole
from app.schemas.support import MessageToContactpersonRequest
from app.services import support_service


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


class TestListRolesWithContacts:
    def test_lists_role_with_description_and_contacts(
        self, db_session: Session, make_user
    ):
        role_name = _unique("planner")
        user = make_user(roles=[role_name])
        role = user.roles[0]
        role.description = "Plant den Dienstplan."
        db_session.commit()

        roles = support_service.list_roles_with_contacts(db_session)
        entry = next(r for r in roles if r.id == role.id)

        assert entry.name == role_name
        assert entry.description == "Plant den Dienstplan."
        assert [u.id for u in entry.users] == [user.id]

    def test_contacts_sorted_by_surname_then_givenname(
        self, db_session: Session, make_user
    ):
        # Legacy's `User` model carries a global `OrderBySurnameGivenname`
        # scope applied to EVERY User query, including this
        # belongsToMany(Role -> User) load -- the dropdown is alphabetical
        # in Legacy regardless of `user_roles` insertion order.
        role_name = _unique("scores")
        third = make_user(roles=[role_name])
        third.surname, third.givenname = "ZEHETNER", "Anna"
        first = make_user(roles=[role_name])
        first.surname, first.givenname = "AMSTETTER", "Bernd"
        second = make_user(roles=[role_name])
        second.surname, second.givenname = "MUELLER", "Carl"
        db_session.commit()

        roles = support_service.list_roles_with_contacts(db_session)
        entry = next(r for r in roles if r.name == role_name)

        assert [u.id for u in entry.users] == [first.id, second.id, third.id]

    def test_has_email_reflects_verified_email_only(
        self, db_session: Session, make_user
    ):
        role_name = _unique("disponent")
        verified = make_user(roles=[role_name])
        verified.email_verified_at = datetime.now(UTC)
        unverified = make_user(roles=[role_name], verified=False)
        db_session.commit()

        roles = support_service.list_roles_with_contacts(db_session)
        entry = next(r for r in roles if r.name == role_name)
        by_id = {u.id: u.has_email for u in entry.users}

        assert by_id[verified.id] is True
        assert by_id[unverified.id] is False

    def test_role_without_users_still_lists_with_empty_contacts(
        self, db_session: Session, make_user
    ):
        role_name = _unique("billing")
        # Creates the role via the roles=[...] side channel without ever
        # assigning a user to it, by immediately removing the membership --
        # simplest way to get a real, persisted, contact-less Role row.
        user = make_user(roles=[role_name])
        role = user.roles[0]
        db_session.execute(
            delete(UserRole).where(
                UserRole.user_id == user.id, UserRole.role_id == role.id
            )
        )
        db_session.commit()

        roles = support_service.list_roles_with_contacts(db_session)
        entry = next(r for r in roles if r.id == role.id)
        assert entry.users == []

    def test_query_count_does_not_scale_with_role_or_contact_count(
        self, db_session: Session, make_user, count_queries
    ):
        role_name = _unique("scores")
        for _ in range(5):
            make_user(roles=[role_name])

        with count_queries() as counter:
            support_service.list_roles_with_contacts(db_session)
        baseline = counter.count

        other_role = _unique("shorturls")
        for _ in range(5):
            make_user(roles=[other_role])

        with count_queries() as counter:
            support_service.list_roles_with_contacts(db_session)

        assert counter.count == baseline


class TestSendMessageToContactperson:
    def _data(
        self, *, recipient_id: int, message: str = "Bitte um Rückruf."
    ) -> MessageToContactpersonRequest:
        return MessageToContactpersonRequest(recipient_id=recipient_id, message=message)

    def test_returns_email_sender_and_message_for_verified_recipient(
        self, db_session: Session, make_user
    ):
        sender = make_user()
        recipient = make_user(email="kontakt@example.test")
        recipient.email_verified_at = datetime.now(UTC)
        db_session.commit()

        result = support_service.send_message_to_contactperson(
            db_session, sender, self._data(recipient_id=recipient.id)
        )

        assert result is not None
        to_emails, sender_name, message = result
        assert to_emails == ["kontakt@example.test"]
        assert sender_name == f"{sender.surname}, {sender.givenname}"
        assert message == "Bitte um Rückruf."

    def test_silent_noop_for_unverified_recipient(self, db_session: Session, make_user):
        sender = make_user()
        recipient = make_user(verified=False)

        result = support_service.send_message_to_contactperson(
            db_session, sender, self._data(recipient_id=recipient.id)
        )

        assert result is None

    def test_silent_noop_for_recipient_without_email(
        self, db_session: Session, make_user
    ):
        sender = make_user()
        recipient = make_user()
        recipient.email = None
        recipient.email_verified_at = datetime.now(UTC)
        db_session.commit()

        result = support_service.send_message_to_contactperson(
            db_session, sender, self._data(recipient_id=recipient.id)
        )

        assert result is None

    def test_silent_noop_for_nonexistent_recipient(
        self, db_session: Session, make_user
    ):
        sender = make_user()

        result = support_service.send_message_to_contactperson(
            db_session, sender, self._data(recipient_id=0)
        )

        assert result is None
