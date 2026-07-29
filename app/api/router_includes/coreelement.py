from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import ensure_permission
from app.api.deps import get_current_user
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.coreelement import (
    CoreelementRequest,
    CoreelementResponse,
    CoreelementType,
)
from app.services import coreelement_service
from app.services.coreelement_service import (
    CoreelementInUseError,
    CoreelementModel,
    CoreelementNotFoundError,
    CoreelementValidationError,
)

coreelement_router = APIRouter()

# All six Legacy Policies (Instrument/Voice/Choirjob/Location/Propriumelement/
# Role `maintain`) resolve to the exact same condition (administrator-Flag,
# see project_osa_legacy_domain_map memory) -- routed through the central
# PERMISSION_RULES matrix regardless, so a future policy change for a single
# type is a one-line edit in permission_service.py, not a new branch here.
_PERMISSION_BY_TYPE: dict[CoreelementType, str] = {
    CoreelementType.instrument: "instrumentMaintain",
    CoreelementType.voice: "voiceMaintain",
    CoreelementType.choirjob: "choirjobMaintain",
    CoreelementType.location: "locationMaintain",
    CoreelementType.propriumelement: "propriumelementMaintain",
    CoreelementType.role: "roleMaintain",
}

_IN_USE_DETAIL = "Das Element kann nicht gelöscht werden, da es noch in Verwendung ist."


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Nicht gefunden."
    )


def _to_response(item: CoreelementModel) -> CoreelementResponse:
    return CoreelementResponse(
        id=item.id,
        name=item.name,
        order=item.order,
        label=getattr(item, "label", None),
        description=getattr(item, "description", None),
        address=getattr(item, "address", None),
        color=getattr(item, "color", None),
    )


@coreelement_router.get("/{element_type}")
def list_items(
    element_type: CoreelementType,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[CoreelementResponse]:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    items = coreelement_service.list_coreelements(db, element_type)
    return [_to_response(item) for item in items]


@coreelement_router.post("/{element_type}", status_code=status.HTTP_201_CREATED)
def create_item(
    element_type: CoreelementType,
    data: CoreelementRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CoreelementResponse:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    try:
        item = coreelement_service.create_coreelement(db, element_type, data)
    except CoreelementValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None
    return _to_response(item)


@coreelement_router.put("/{element_type}/{element_id}")
def update_item(
    element_type: CoreelementType,
    element_id: int,
    data: CoreelementRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CoreelementResponse:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    try:
        item = coreelement_service.update_coreelement(
            db, element_type, element_id, data
        )
    except CoreelementNotFoundError:
        raise _not_found() from None
    except CoreelementValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None
    return _to_response(item)


@coreelement_router.delete("/{element_type}/{element_id}")
def delete_item(
    element_type: CoreelementType,
    element_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    try:
        coreelement_service.delete_coreelement(db, element_type, element_id)
    except CoreelementNotFoundError:
        raise _not_found() from None
    except CoreelementInUseError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail([("general", _IN_USE_DETAIL)]),
        ) from None
    return {"status": "ok", "message": "Element wurde gelöscht."}


@coreelement_router.post("/{element_type}/{element_id}/move/{direction}")
def move_item(
    element_type: CoreelementType,
    element_id: int,
    direction: Literal["up", "down"],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[CoreelementResponse]:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    try:
        items = coreelement_service.move_coreelement(
            db, element_type, element_id, direction
        )
    except CoreelementNotFoundError:
        raise _not_found() from None
    return [_to_response(item) for item in items]
