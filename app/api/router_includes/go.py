from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services import shorturl_service

go_router = APIRouter()

# Fixed external marketing site Legacy redirects the bare go.-domain root
# to (`Route::redirect('/', 'https://www.hochamt.at')`). Deliberately a
# literal, not a Settings field: it is the church's own public website,
# identical in every environment (dev and prod both point real visitors
# at the same real site) -- unlike Settings.shorturl_domain, there is no
# deployment-topology reason for this value to ever vary.
_ROOT_REDIRECT_TARGET = "https://www.hochamt.at"

# `RedirectResponse` defaults to 307 -- Legacy's `redirect()`/
# `Route::redirect()` both default to 302, so it must be passed explicitly
# on every redirect below for Legacy parity.
_FOUND = status.HTTP_302_FOUND


@go_router.get("/")
def go_root() -> RedirectResponse:
    return RedirectResponse(_ROOT_REDIRECT_TARGET, status_code=_FOUND)


@go_router.get("/{path:path}")
def go_resolve(
    path: str,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Public, unauthenticated redirect lookup -- 1:1 GoController::go(),
    minus its `path === 'listAll'` special case (an unauthenticated dump
    of every stored target URL). That case is deliberately not ported: the
    authenticated management page (`/shorturls`, role `shorturls`) already
    shows the identical list, properly permission-gated. Without the
    special case, a request for "/go/listAll" simply falls through to the
    normal lookup below and 404s like any other unknown path -- the leak
    is closed structurally, not patched with a new auth check on what is
    supposed to be a public route."""
    target = shorturl_service.resolve_and_record_hit(db, path)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(target, status_code=_FOUND)
