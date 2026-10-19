"""Query parameter types shared by several routers."""

from typing import Annotated

from fastapi import Depends, Query

from app.schemas.pagination import MAX_PAGE_OFFSET, MAX_PAGE_SIZE, PageParams

SEARCH_TERM_MAX_LENGTH = 64

# The search term is split into words that each become a LIKE condition, so
# its length is bounded at the boundary instead of in the service.
SearchTerm = Annotated[str, Query(min_length=1, max_length=SEARCH_TERM_MAX_LENGTH)]

CALENDAR_YEAR_MIN = 2000
CALENDAR_YEAR_MAX = 2100

# The month lists build calendar dates from the year, so it is bounded to the
# range the application can hold data for instead of accepting any integer.
CalendarYear = Annotated[int, Query(ge=CALENDAR_YEAR_MIN, le=CALENDAR_YEAR_MAX)]


def get_page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = MAX_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=MAX_PAGE_OFFSET)] = 0,
) -> PageParams:
    """The default limit equals the maximum: a client that sends no paging
    parameters gets the first page of the largest size, never an unbounded
    result."""
    return PageParams(limit=limit, offset=offset)


PageDep = Annotated[PageParams, Depends(get_page_params)]
