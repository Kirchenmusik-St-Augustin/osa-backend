import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.query_params import PageDep, SearchTerm
from app.db.database import get_db
from app.schemas.artist import ArtistRequest, ArtistResponse, ArtistSearchResult
from app.schemas.pagination import Page
from app.services import artist_service

# Every artist route needs the same permission and none uses the user object,
# so the guard is declared once for the whole router.
artist_router = APIRouter(dependencies=[Depends(require_permission("artistMaintain"))])


@artist_router.get("/search")
def search_artists(
    q: SearchTerm,
    db: Annotated[Session, Depends(get_db)],
) -> list[ArtistSearchResult]:
    return [
        artist_service.to_search_result(artist)
        for artist in artist_service.search_artists(db, q)
    ]


@artist_router.post("", status_code=status.HTTP_201_CREATED)
def create_artist(
    data: ArtistRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ArtistResponse:
    return artist_service.to_response(artist_service.create_artist(db, data))


@artist_router.get("/composers")
def list_composer_artists(
    db: Annotated[Session, Depends(get_db)],
    page: PageDep,
) -> Page[ArtistSearchResult]:
    paged = artist_service.list_composer_artists(db, page)
    return Page.of(paged.map(artist_service.to_search_result), page)


@artist_router.get("/{artist_id}")
def get_artist(
    artist_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> ArtistResponse:
    return artist_service.to_response(artist_service.get_artist(db, artist_id))


@artist_router.put("/{artist_id}")
def update_artist(
    artist_id: uuid.UUID,
    data: ArtistRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ArtistResponse:
    return artist_service.to_response(artist_service.update_artist(db, artist_id, data))


@artist_router.delete("/{artist_id}")
def delete_artist(
    artist_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    artist_service.delete_artist(db, artist_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}
