from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core import mailer
from app.db.models.sent_email import SentEmail
from app.schemas.score import ScoreRequest
from app.services import score_service, statistics_service


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

    def test_scores_counts_all_score_rows(self, db_session: Session):
        before = statistics_service.get_statistics(db_session).scores
        defaults = score_service.get_defaults()
        score_service.create_score(
            db_session,
            ScoreRequest(
                **{
                    **defaults,
                    "kasten": "A",
                    "boxnr": "1",
                    "werk": "Testwerk",
                    "inhalt": "Partitur",
                }
            ),
        )

        result = statistics_service.get_statistics(db_session)

        assert result.scores == before + 1
