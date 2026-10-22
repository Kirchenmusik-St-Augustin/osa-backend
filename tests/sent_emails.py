"""Builds a SentEmail row with the columns every mail has, so a test only
names the ones it cares about."""

from app.db.models.sent_email import SentEmail


def sent_email(**fields: object) -> SentEmail:
    values: dict[str, object] = {
        "mail_from": "no-reply@example.test",
        "subject": "Betreff",
        "body": "<p>Text</p>",
        "template_key": "test-mail",
    }
    values.update(fields)
    return SentEmail(**values)
