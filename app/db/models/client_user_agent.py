from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ClientUserAgent(Base):
    """Mirrors legacy `client_user_agents` exactly (Phase 1) -- a dedup table
    for raw User-Agent header strings, referenced by `request_logs.
    client_user_agent_id`. No timestamps (legacy: `public $timestamps =
    false`)."""

    __tablename__ = "client_user_agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    string: Mapped[str]
