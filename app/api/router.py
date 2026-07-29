"""Aggregates all domain routers into a single api_router, mounted in
main.py."""

from fastapi import APIRouter

from app.api.router_includes.artist import artist_router
from app.api.router_includes.auth import auth_router
from app.api.router_includes.coreelement import coreelement_router
from app.api.router_includes.ordinariumwork import ordinariumwork_router
from app.api.router_includes.propriumwork import propriumwork_router

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
