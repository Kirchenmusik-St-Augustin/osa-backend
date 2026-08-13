from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.sql_inspector import TableDataOutput
from app.services import sql_inspector_service
from app.services.sql_inspector_service import TableNotFoundError

sql_inspector_router = APIRouter()

_VIEW = Depends(require_permission("sqlInspectorView"))
_NOT_FOUND_DETAIL = "Tabelle nicht gefunden."


@sql_inspector_router.get("/tables")
def list_tables(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> list[str]:
    return sql_inspector_service.get_valid_tables(db)


@sql_inspector_router.get("/tables/{table_name}")
def get_table_data(
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> TableDataOutput:
    try:
        return sql_inspector_service.get_table_data(db, table_name, page, page_size)
    except TableNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
