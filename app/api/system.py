from fastapi import APIRouter

system_router = APIRouter(tags=["System"])


@system_router.get("/")
def read_root() -> dict[str, str]:
    """Liveness check: process is up and able to serve requests."""
    return {"status": "ok", "message": "osa-backend is running."}
