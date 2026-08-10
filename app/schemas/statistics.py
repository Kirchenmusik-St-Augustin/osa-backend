from pydantic import BaseModel


class StatisticsEmailOutput(BaseModel):
    """The kill-switch status plus its raw `sent` count -- `sent` is
    exclusive to this endpoint (see mailer.MailKillSwitchStatus docstring),
    not exposed via GET /auth/me."""

    active: bool
    period_days: int
    threshold: int
    sent: int


class StatisticsOutput(BaseModel):
    """1:1 Legacy's `StatisticsController::statistics()` -- deliberately
    WITHOUT a `scores` field (Legacy's "Partituren im Archiv" /
    `Score::count()`): the Scores domain (Schritt 8) doesn't exist in
    osa-backend yet. Sequencing gap, not a bug -- same precedent as
    Ordinariumwork/Propriumwork's missing "Aufführungen" section before
    Schritt 5 landed. Add the field once Schritt 8 ships."""

    users: int
    performances: int
    ordinariumworks: int
    propriumworks: int
    email: StatisticsEmailOutput
