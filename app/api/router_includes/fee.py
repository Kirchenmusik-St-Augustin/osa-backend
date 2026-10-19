import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.query_params import PageDep
from app.db.database import get_db
from app.schemas.fee import FeeRequest, FeeResponse
from app.schemas.pagination import Page
from app.services import fee_service

# Every fee route needs the same permission and none uses the user object, so
# the guard is declared once for the whole router.
fee_router = APIRouter(dependencies=[Depends(require_permission("feeMaintain"))])


@fee_router.get("")
def list_fees(
    db: Annotated[Session, Depends(get_db)],
    page: PageDep,
) -> Page[FeeResponse]:
    return Page.of(fee_service.list_fees_page(db, page), page)


@fee_router.post("", status_code=status.HTTP_201_CREATED)
def create_fee(
    data: FeeRequest,
    db: Annotated[Session, Depends(get_db)],
) -> FeeResponse:
    return fee_service.create_fee(db, data)


@fee_router.put("/{fee_id}")
def update_fee(
    fee_id: uuid.UUID,
    data: FeeRequest,
    db: Annotated[Session, Depends(get_db)],
) -> FeeResponse:
    return fee_service.update_fee(db, fee_id, data)


@fee_router.delete("/{fee_id}")
def delete_fee(
    fee_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    fee_service.delete_fee(db, fee_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}
