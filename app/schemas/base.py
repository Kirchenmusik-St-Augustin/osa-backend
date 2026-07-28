from pydantic import BaseModel, ConfigDict


class StrictInputModel(BaseModel):
    """Base for every Auth-domain request body (CLAUDE.md: extra="forbid",
    strict=True for all input models)."""

    model_config = ConfigDict(extra="forbid", strict=True)
