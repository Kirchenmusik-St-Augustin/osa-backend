from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.schemas.pagination import PagedRows, PageParams

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.orm import Session


def select_page[T](
    db: Session, stmt: Select[tuple[T]], page: PageParams
) -> PagedRows[T]:
    """Runs `stmt` for one page and counts the whole result with a second
    statement. The ordering of `stmt` must be total (end it with the primary
    key), otherwise rows can repeat or vanish between two pages."""
    total = db.execute(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ).scalar_one()
    rows = db.execute(stmt.limit(page.limit).offset(page.offset)).scalars().all()
    return PagedRows(rows=rows, total=total)
