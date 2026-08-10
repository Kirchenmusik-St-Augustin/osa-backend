from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core import mailer
from app.db.models.sent_email import SentEmail
from app.services import statistics_service


class TestGetStatistics:
    def test_users_excludes_soft_deleted(self, db_session: Session, make_user):
        before = statistics_service.get_statistics(db_session).users
        active = make_user()
        deleted = make_user()
        deleted.deleted_at = datetime.now(UTC)
        db_session.commit()

        result = statistics_service.get_statistics(db_session)

        assert result.users == before + 1
        assert active.id  # sanity: the active user really got persisted

    def test_email_reflects_the_same_source_as_auth_me(
        self, db_session: Session, monkeypatch
    ):
        # /statistics's "sent" counter and /auth/me's "active" flag are
        # both computed by the exact same mailer.get_kill_switch_status()
        # call -- they must never disagree.
        monkeypatch.setenv("MAIL_KILL_SWITCH_THRESHOLD", "1")
        db_session.add(SentEmail(to="a@example.test", created_at=datetime.now(UTC)))
        db_session.commit()

        result = statistics_service.get_statistics(db_session)
        kill_switch = mailer.get_kill_switch_status(db_session)

        assert result.email.active == kill_switch.active
        assert result.email.sent == kill_switch.sent
        assert result.email.threshold == kill_switch.threshold
        assert result.email.period_days == kill_switch.period_days

    def test_has_no_scores_field(self, db_session: Session):
        # Deliberate gap (Schritt 8 doesn't exist yet, see
        # StatisticsOutput's docstring) -- guards against silently adding
        # a wrong/placeholder value instead of the real thing later.
        result = statistics_service.get_statistics(db_session)
        assert not hasattr(result, "scores")
