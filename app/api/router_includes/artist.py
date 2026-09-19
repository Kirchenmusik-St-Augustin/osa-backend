import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.artist import Artist
from app.db.models.user import User
from app.schemas.artist import ArtistRequest, ArtistResponse, ArtistSearchResult
from app.services import artist_service
from app.services.artist_service import label_for

artist_router = APIRouter()

_MAINTAIN = Depends(require_permission("artistMaintain"))


def _to_response(artist: Artist) -> ArtistResponse:
    return ArtistResponse(
        id=artist.id,
        surname=artist.surname or "",
        givenname=artist.givenname or "",
        description=artist.description,
        birthyear=artist.birthyear,
        deathyear=artist.deathyear,
        composer=artist.composer,
        conductor=artist.conductor,
    )


@artist_router.get("/search")
def search_artists(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[ArtistSearchResult]:
    results = artist_service.search_artists(db, q)
    return [
        ArtistSearchResult(id=artist.id, label=label_for(artist)) for artist in results
    ]


@artist_router.post("", status_code=status.HTTP_201_CREATED)
def create_artist(
    data: ArtistRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ArtistResponse:
    artist = artist_service.create_artist(db, data)
    return _to_response(artist)


@artist_router.get("/composers")
def list_composer_artists(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[ArtistSearchResult]:
    artists = artist_service.list_composer_artists(db)
    return [
        ArtistSearchResult(id=artist.id, label=label_for(artist)) for artist in artists
    ]


@artist_router.get("/{artist_id}")
def get_artist(
    artist_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ArtistResponse:
    artist = artist_service.get_artist(db, artist_id)
    return _to_response(artist)


@artist_router.put("/{artist_id}")
def update_artist(
    artist_id: uuid.UUID,
    data: ArtistRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ArtistResponse:
    artist = artist_service.update_artist(db, artist_id, data)
    return _to_response(artist)


@artist_router.delete("/{artist_id}")
def delete_artist(
    artist_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    artist_service.delete_artist(db, artist_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}
