from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.fee import FeeRequest, FeeResponse
from app.services import fee_service
from app.services.fee_service import FeeNotFoundError, FeeValidationError

fee_router = APIRouter()

_MAINTAIN = Depends(require_permission("feeMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."


@fee_router.get("")
def list_fees(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[FeeResponse]:
    return fee_service.list_fees(db)


@fee_router.post("", status_code=status.HTTP_201_CREATED)
def create_fee(
    data: FeeRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> FeeResponse:
    try:
        return fee_service.create_fee(db, data)
    except FeeValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@fee_router.put("/{fee_id}")
def update_fee(
    fee_id: int,
    data: FeeRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> FeeResponse:
    try:
        return fee_service.update_fee(db, fee_id, data)
    except FeeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except FeeValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@fee_router.delete("/{fee_id}")
def delete_fee(
    fee_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    try:
        fee_service.delete_fee(db, fee_id)
    except FeeNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return {"status": "ok", "message": "Element wurde gelöscht."}
