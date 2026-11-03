from app.schemas.pagination import Page, PagedRows, PageParams


def test_to_page_carries_the_rows_the_total_and_the_requested_window():
    paged = PagedRows(rows=["a", "b"], total=7)

    page = paged.to_page(PageParams(limit=2, offset=4))

    assert page.model_dump() == {
        "items": ["a", "b"],
        "total": 7,
        "limit": 2,
        "offset": 4,
    }


def test_to_page_of_a_mapped_page_converts_every_row_and_keeps_the_total():
    paged = PagedRows(rows=[1, 2, 3], total=30).map(str)

    page = paged.to_page(PageParams(limit=3, offset=0))

    assert page.items == ["1", "2", "3"]
    assert page.total == 30


def test_to_page_of_an_empty_result_is_an_empty_envelope():
    page = PagedRows[int](rows=[], total=0).to_page(PageParams(limit=50, offset=100))

    assert isinstance(page, Page)
    assert page.model_dump() == {"items": [], "total": 0, "limit": 50, "offset": 100}
