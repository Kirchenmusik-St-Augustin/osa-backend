from pydantic import BaseModel


class EnvironmentOutput(BaseModel):
    """Current backend deployment stage (development/test/qa/production),
    shown next to the frontend's own stage on the profile page so a
    mismatch between the two is visible at a glance."""

    environment: str
