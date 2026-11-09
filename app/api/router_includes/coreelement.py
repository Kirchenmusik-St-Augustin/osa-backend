import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, ensure_permission, get_verified_user
from app.api.query_params import PageDep
from app.db.database import get_db
from app.schemas.coreelement import (
    CoreelementRequest,
    CoreelementResponse,
    CoreelementType,
)
from app.schemas.pagination import Page
from app.services import coreelement_service

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


def _require_maintain_permission(
    element_type: CoreelementType,
    current_user: Annotated[AuthUser, Depends(get_verified_user)],
) -> None:
    """Per-type maintain permission as a route dependency, so it is checked
    before the request body is validated: a caller without the permission
    gets 403, not a 422 that describes the schema."""
    ensure_permission(current_user, _PERMISSION_BY_TYPE[element_type])


coreelement_router = APIRouter(dependencies=[Depends(_require_maintain_permission)])


@coreelement_router.get("/{element_type}")
def list_items(
    element_type: CoreelementType,
    db: Annotated[Session, Depends(get_db)],
    page: PageDep,
) -> Page[CoreelementResponse]:
    paged = coreelement_service.list_coreelements_page(db, element_type, page)
    return paged.map(coreelement_service.to_response).to_page(page)


@coreelement_router.post("/{element_type}", status_code=status.HTTP_201_CREATED)
def create_item(
    element_type: CoreelementType,
    data: CoreelementRequest,
    db: Annotated[Session, Depends(get_db)],
) -> CoreelementResponse:
    item = coreelement_service.create_coreelement(db, element_type, data)
    return coreelement_service.to_response(item)


@coreelement_router.put("/{element_type}/{element_id}")
def update_item(
    element_type: CoreelementType,
    element_id: uuid.UUID,
    data: CoreelementRequest,
    db: Annotated[Session, Depends(get_db)],
) -> CoreelementResponse:
    item = coreelement_service.update_coreelement(db, element_type, element_id, data)
    return coreelement_service.to_response(item)


@coreelement_router.delete("/{element_type}/{element_id}")
def delete_item(
    element_type: CoreelementType,
    element_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    coreelement_service.delete_coreelement(db, element_type, element_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}


@coreelement_router.post("/{element_type}/{element_id}/move/{direction}")
def move_item(
    element_type: CoreelementType,
    element_id: uuid.UUID,
    direction: Literal["up", "down"],
    db: Annotated[Session, Depends(get_db)],
) -> list[CoreelementResponse]:
    items = coreelement_service.move_coreelement(
        db, element_type, element_id, direction
    )
    return [coreelement_service.to_response(item) for item in items]
