# pyright: reportUnusedImport=false
"""All models must be imported here so SQLAlchemy's mapper registry can
resolve string-based relationship() arguments (e.g. User.roles' primaryjoin
referencing "UserRole" by name) regardless of which model happens to be
queried first. Import this module once, early, at app startup (see
main.py) -- 1:1 vb-api pattern (app/db/base.py)."""

from app.db.database import Base  # noqa: F401
from app.db.models.auth_log import AuthLog  # noqa: F401
from app.db.models.personal_access_token import PersonalAccessToken  # noqa: F401
from app.db.models.role import Role  # noqa: F401
from app.db.models.user import User  # noqa: F401
from app.db.models.user_role import UserRole  # noqa: F401
