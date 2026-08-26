# pyright: reportUnusedImport=false
"""All models must be imported here so SQLAlchemy's mapper registry can
resolve string-based relationship() arguments (e.g. User.roles' primaryjoin
referencing "UserRole" by name) regardless of which model happens to be
queried first. Import this module once, early, at app startup (see
main.py)."""

from app.db.database import Base  # noqa: F401
from app.db.models.artist import Artist  # noqa: F401
from app.db.models.auth_log import AuthLog  # noqa: F401
from app.db.models.booking import Booking  # noqa: F401
from app.db.models.booking_log import BookingLog  # noqa: F401
from app.db.models.booking_request import BookingRequest  # noqa: F401
from app.db.models.choirjob import Choirjob  # noqa: F401
from app.db.models.client_user_agent import ClientUserAgent  # noqa: F401
from app.db.models.fee import Fee  # noqa: F401
from app.db.models.instrument import Instrument  # noqa: F401
from app.db.models.location import Location  # noqa: F401
from app.db.models.oauth2_binding import Oauth2Binding  # noqa: F401
from app.db.models.ordinariumwork import Ordinariumwork  # noqa: F401
from app.db.models.ordinariumwork_position import OrdinariumworkPosition  # noqa: F401
from app.db.models.password_reset_token import PasswordResetToken  # noqa: F401
from app.db.models.performance import Performance  # noqa: F401
from app.db.models.performance_position import PerformancePosition  # noqa: F401
from app.db.models.performance_proprium import PerformanceProprium  # noqa: F401
from app.db.models.performance_rehearsal import PerformanceRehearsal  # noqa: F401
from app.db.models.personal_access_token import PersonalAccessToken  # noqa: F401
from app.db.models.propriumelement import Propriumelement  # noqa: F401
from app.db.models.propriumwork import Propriumwork  # noqa: F401
from app.db.models.request_log import RequestLog  # noqa: F401
from app.db.models.role import Role  # noqa: F401
from app.db.models.score import Score  # noqa: F401
from app.db.models.sent_email import SentEmail  # noqa: F401
from app.db.models.shorturl import Shorturl  # noqa: F401
from app.db.models.user import User  # noqa: F401
from app.db.models.user_position import UserPosition  # noqa: F401
from app.db.models.user_role import UserRole  # noqa: F401
from app.db.models.voice import Voice  # noqa: F401
