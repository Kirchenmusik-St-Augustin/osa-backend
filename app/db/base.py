# pyright: reportUnusedImport=false
"""All models must be imported here so SQLAlchemy's mapper registry can
resolve string-based relationship() arguments (e.g. User.roles' primaryjoin
referencing "UserRole" by name) regardless of which model happens to be
queried first. Import this module once, early, at app startup (see
main.py) -- 1:1 vb-api pattern (app/db/base.py)."""

from app.db.database import Base  # noqa: F401
from app.db.models.artist import Artist  # noqa: F401
from app.db.models.auth_log import AuthLog  # noqa: F401
from app.db.models.choirjob import Choirjob  # noqa: F401
from app.db.models.instrument import Instrument  # noqa: F401
from app.db.models.location import Location  # noqa: F401
from app.db.models.oauth2_binding import Oauth2Binding  # noqa: F401
from app.db.models.ordinariumwork import Ordinariumwork  # noqa: F401
from app.db.models.ordinariumwork_position import OrdinariumworkPosition  # noqa: F401
from app.db.models.password_reset_token import PasswordResetToken  # noqa: F401
from app.db.models.personal_access_token import PersonalAccessToken  # noqa: F401
from app.db.models.propriumelement import Propriumelement  # noqa: F401
from app.db.models.propriumwork import Propriumwork  # noqa: F401
from app.db.models.role import Role  # noqa: F401
from app.db.models.sent_email import SentEmail  # noqa: F401
from app.db.models.user import User  # noqa: F401
from app.db.models.user_role import UserRole  # noqa: F401
from app.db.models.voice import Voice  # noqa: F401
