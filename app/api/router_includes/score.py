from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.score import (
    ScoreFieldConfig,
    ScoreRequest,
    ScoreResponse,
    ScoreSearchResult,
)
from app.services import score_service
from app.services.score_service import ScoreNotFoundError, ScoreValidationError

score_router = APIRouter()

_MAINTAIN = Depends(require_permission("scoreMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."

# No DELETE route -- Legacy's own route registration excludes `destroy`
# entirely (Route::resource(...)->except(['destroy'])), see score.py
# model's docstring. Deliberately no stub here either.


@score_router.get("/fields-config")
def get_fields_config(
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, ScoreFieldConfig]:
    return score_service.get_fields_config()


@score_router.get("/defaults")
def get_defaults(
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str | int]:
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
    score_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ScoreResponse:
    try:
        return score_service.get_score(db, score_id)
    except ScoreNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None


@score_router.post("", status_code=status.HTTP_201_CREATED)
def create_score(
    data: ScoreRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ScoreResponse:
    try:
        return score_service.create_score(db, data)
    except ScoreValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@score_router.put("/{score_id}")
def update_score(
    score_id: int,
    data: ScoreRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ScoreResponse:
    try:
        return score_service.update_score(db, score_id, data)
    except ScoreNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except ScoreValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None
