from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.artist import Artist
from app.db.models.user import User
from app.schemas.artist import ArtistRequest, ArtistResponse, ArtistSearchResult
from app.services import artist_service
from app.services.artist_service import (
    ArtistInUseError,
    ArtistNotFoundError,
    ArtistValidationError,
    label_for,
)

artist_router = APIRouter()

_MAINTAIN = Depends(require_permission("artistMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."
_IN_USE_DETAIL = "Das Element kann nicht gelöscht werden, da es noch in Verwendung ist."


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
    try:
        artist = artist_service.create_artist(db, data)
    except ArtistValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None
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
    artist_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ArtistResponse:
    try:
        artist = artist_service.get_artist(db, artist_id)
    except ArtistNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return _to_response(artist)


@artist_router.put("/{artist_id}")
def update_artist(
    artist_id: int,
    data: ArtistRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ArtistResponse:
    try:
        artist = artist_service.update_artist(db, artist_id, data)
    except ArtistNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except ArtistValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None
    return _to_response(artist)


@artist_router.delete("/{artist_id}")
def delete_artist(
    artist_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    try:
        artist_service.delete_artist(db, artist_id)
    except ArtistNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except ArtistInUseError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail([("general", _IN_USE_DETAIL)]),
        ) from None
    return {"status": "ok", "message": "Element wurde gelöscht."}
