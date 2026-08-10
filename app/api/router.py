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
from app.api.router_includes.support import support_router
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
