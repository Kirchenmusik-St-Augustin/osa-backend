import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import ensure_permission, get_verified_user
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.coreelement import (
    CoreelementRequest,
    CoreelementResponse,
    CoreelementType,
)
from app.services import coreelement_service
from app.services.coreelement_service import CoreelementModel

coreelement_router = APIRouter()

# All six maintain abilities (Instrument/Voice/Choirjob/Location/ Propriumelement/Role)
# resolve to the exact same condition (administrator-Flag) -- routed through the central
# PERMISSION_RULES matrix regardless, so a future policy change for a single type is a
# one-line edit in permission_service.py, not a new branch here.
_PERMISSION_BY_TYPE: dict[CoreelementType, str] = {
    CoreelementType.instrument: "instrumentMaintain",
    CoreelementType.voice: "voiceMaintain",
    CoreelementType.choirjob: "choirjobMaintain",
    CoreelementType.location: "locationMaintain",
    CoreelementType.propriumelement: "propriumelementMaintain",
    CoreelementType.role: "roleMaintain",
}


def _to_response(item: CoreelementModel) -> CoreelementResponse:
    return CoreelementResponse(
        id=item.id,
        name=item.name,
        order=item.order,
        label=getattr(item, "label", None),
        description=getattr(item, "description", None),
        address=getattr(item, "address", None),
        color=getattr(item, "color", None),
        active=getattr(item, "active", None),
    )


@coreelement_router.get("/{element_type}")
def list_items(
    element_type: CoreelementType,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> list[CoreelementResponse]:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    items = coreelement_service.list_coreelements(db, element_type)
    return [_to_response(item) for item in items]


@coreelement_router.post("/{element_type}", status_code=status.HTTP_201_CREATED)
def create_item(
    element_type: CoreelementType,
    data: CoreelementRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> CoreelementResponse:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    item = coreelement_service.create_coreelement(db, element_type, data)
    return _to_response(item)


@coreelement_router.put("/{element_type}/{element_id}")
def update_item(
    element_type: CoreelementType,
    element_id: uuid.UUID,
    data: CoreelementRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> CoreelementResponse:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    item = coreelement_service.update_coreelement(db, element_type, element_id, data)
    return _to_response(item)


@coreelement_router.delete("/{element_type}/{element_id}")
def delete_item(
    element_type: CoreelementType,
    element_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> dict[str, str]:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    coreelement_service.delete_coreelement(db, element_type, element_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}


@coreelement_router.post("/{element_type}/{element_id}/move/{direction}")
def move_item(
    element_type: CoreelementType,
    element_id: uuid.UUID,
    direction: Literal["up", "down"],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> list[CoreelementResponse]:
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])
    items = coreelement_service.move_coreelement(
        db, element_type, element_id, direction
    )
    return [_to_response(item) for item in items]
