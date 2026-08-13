"""Aggregates all domain routers into a single api_router, mounted in
main.py."""

from fastapi import APIRouter

from app.api.router_includes.artist import artist_router
from app.api.router_includes.auth import auth_router
from app.api.router_includes.booking import booking_router
from app.api.router_includes.coreelement import coreelement_router
from app.api.router_includes.fee import fee_router
from app.api.router_includes.ordinariumwork import ordinariumwork_router
from app.api.router_includes.performance import performance_router
from app.api.router_includes.profile import profile_router
from app.api.router_includes.propriumwork import propriumwork_router
from app.api.router_includes.request_log import request_log_router
from app.api.router_includes.scheduler import scheduler_router
from app.api.router_includes.score import score_router
from app.api.router_includes.sent_email import sent_email_router
from app.api.router_includes.shorturl import shorturl_router
from app.api.router_includes.sql_inspector import sql_inspector_router
from app.api.router_includes.statistics import statistics_router
from app.api.router_includes.support import support_router
from app.api.router_includes.system import system_router
from app.api.router_includes.user import user_router
from app.api.router_includes.user_administration import user_administration_router
from app.api.router_includes.userdirectory import userdirectory_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(
    coreelement_router, prefix="/coreelements", tags=["coreelements"]
)
api_router.include_router(artist_router, prefix="/artists", tags=["artists"])
api_router.include_router(
    ordinariumwork_router, prefix="/ordinariumworks", tags=["ordinariumworks"]
)
api_router.include_router(
    propriumwork_router, prefix="/propriumworks", tags=["propriumworks"]
)
api_router.include_router(
    performance_router, prefix="/performances", tags=["performances"]
)
api_router.include_router(booking_router, prefix="/performances", tags=["bookings"])
api_router.include_router(fee_router, prefix="/fees", tags=["fees"])
api_router.include_router(user_router, prefix="/users", tags=["users"])
api_router.include_router(
    userdirectory_router, prefix="/userdirectory", tags=["userdirectory"]
)
api_router.include_router(
    user_administration_router,
    prefix="/administrator/users",
    tags=["user-administration"],
)
api_router.include_router(profile_router, prefix="/profile", tags=["profile"])
api_router.include_router(support_router, prefix="/support", tags=["support"])
api_router.include_router(
    sent_email_router, prefix="/administrator/sent-emails", tags=["sent-emails"]
)
api_router.include_router(
    request_log_router, prefix="/administrator/request-logs", tags=["request-logs"]
)
api_router.include_router(
    sql_inspector_router,
    prefix="/administrator/sql-inspector",
    tags=["sql-inspector"],
)
api_router.include_router(
    scheduler_router, prefix="/administrator/scheduler", tags=["scheduler"]
)
api_router.include_router(statistics_router, prefix="/statistics", tags=["statistics"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
api_router.include_router(shorturl_router, prefix="/shorturls", tags=["shorturls"])
api_router.include_router(score_router, prefix="/scores", tags=["scores"])
