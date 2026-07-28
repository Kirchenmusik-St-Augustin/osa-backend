"""Aggregates all domain routers into a single api_router, mounted in
main.py. Empty in this scaffolding step -- the first domain slice adds its
router under app/api/router_includes/ (created then, not now) and includes
it here, mirroring the vb-fastapi-vue sister project's shape."""

from fastapi import APIRouter

api_router = APIRouter()
