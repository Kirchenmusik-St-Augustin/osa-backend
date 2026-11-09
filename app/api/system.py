from fastapi import APIRouter

liveness_router = APIRouter(tags=["System"])


@liveness_router.get("/")
def read_root() -> dict[str, str]:
    """Liveness check: process is up and able to serve requests."""
    return {"status": "ok", "message": "osa-backend is running."}
