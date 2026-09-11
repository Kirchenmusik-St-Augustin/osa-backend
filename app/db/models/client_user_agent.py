import uuid

from sqlalchemy.orm import Mapped

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class ClientUserAgent(Base):
    """Mirrors legacy `client_user_agents` exactly (Phase 1) -- a dedup table
    for raw User-Agent header strings, referenced by `request_logs.
    client_user_agent_id`. No timestamps (legacy: `public $timestamps =
    false`)."""

    __tablename__ = "client_user_agents"

    id: Mapped[uuid.UUID] = uuid_pk()
    string: Mapped[str]
