"""Aggregates all domain routers into a single api_router, mounted in
main.py."""

from fastapi import APIRouter

from app.api.router_includes.auth import auth_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
