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
    """Row counts shown on the Statistics page."""

    users: int
    performances: int
    ordinariumworks: int
    propriumworks: int
    scores: int
    email: StatisticsEmailOutput
