from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services import shorturl_service

go_router = APIRouter()

# Fixed external marketing site the bare go.-domain root redirects to.
# Deliberately a literal, not a Settings field: it is the church's own public website,
# identical in every environment (dev and prod both point real visitors
# at the same real site) -- unlike Settings.shorturl_domain, there is no
# deployment-topology reason for this value to ever vary.
_ROOT_REDIRECT_TARGET = "https://www.hochamt.at"

# `RedirectResponse` defaults to 307, but every redirect below is a plain
# 302 (Found), so the status must be passed explicitly.
_FOUND = status.HTTP_302_FOUND


@go_router.get("/")
def go_root() -> RedirectResponse:
    return RedirectResponse(_ROOT_REDIRECT_TARGET, status_code=_FOUND)


@go_router.get("/{path:path}")
def go_resolve(
    path: str,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Public, unauthenticated redirect lookup. Deliberately has no
    "list all" special path (an unauthenticated dump of every stored target
    URL): the authenticated management page (`/shorturls`, role
    `shorturls`) already shows the identical list, properly
    permission-gated. A request for "/go/listAll" simply falls through to
    the normal lookup below and 404s like any other unknown path -- there
    is no leak to close with an extra auth check on what is supposed to be
    a public route."""
    target = shorturl_service.resolve_and_record_hit(db, path)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return RedirectResponse(target, status_code=_FOUND)
