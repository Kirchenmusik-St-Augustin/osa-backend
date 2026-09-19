import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.score import (
    ScoreFieldConfig,
    ScoreRequest,
    ScoreResponse,
    ScoreSearchResult,
)
from app.services import score_service

score_router = APIRouter()

_MAINTAIN = Depends(require_permission("scoreMaintain"))

# No DELETE route -- scores are never deleted, see score.py model's
# docstring. Deliberately no stub here either.


@score_router.get("/fields-config")
def get_fields_config(
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, ScoreFieldConfig]:
    return score_service.get_fields_config()


@score_router.get("/defaults")
def get_defaults(
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str | int | None]:
    return score_service.get_defaults()


@score_router.get("/search")
def search_scores(
    q: Annotated[str, Query()],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[ScoreSearchResult]:
    return score_service.search_scores(db, q)


@score_router.get("/{score_id}")
def get_score(
    score_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ScoreResponse:
    return score_service.get_score(db, score_id)


@score_router.post("", status_code=status.HTTP_201_CREATED)
def create_score(
    data: ScoreRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ScoreResponse:
    return score_service.create_score(db, data)


@score_router.put("/{score_id}")
def update_score(
    score_id: uuid.UUID,
    data: ScoreRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ScoreResponse:
    return score_service.update_score(db, score_id, data)
