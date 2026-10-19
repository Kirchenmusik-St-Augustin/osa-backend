from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

MAX_PAGE_SIZE = 500
# The database takes the offset as a bigint; a bound far above any real table
# keeps an absurd value from failing in the driver.
MAX_PAGE_OFFSET = 1_000_000


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


@dataclass(frozen=True)
class PagedRows[T]:
    """One page of rows plus the size of the whole result, as returned by the
    services. The router turns it into a `Page`."""

    rows: Sequence[T]
    total: int

    def map[U](self, convert: Callable[[T], U]) -> PagedRows[U]:
        return PagedRows(rows=[convert(row) for row in self.rows], total=self.total)


class Page[T](BaseModel):
    """Envelope of every paginated list: the requested page and the number of
    rows of the whole result, so a client can tell whether more pages exist."""

    items: list[T]
    total: int
    limit: int
    offset: int

    @classmethod
    def of(cls, paged: PagedRows[T], params: PageParams) -> Page[T]:
        return cls(
            items=list(paged.rows),
            total=paged.total,
            limit=params.limit,
            offset=params.offset,
        )
