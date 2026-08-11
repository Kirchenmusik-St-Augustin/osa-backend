from app.core.human_names import normalize_givenname, normalize_surname


def test_normalize_surname_uppercases():
    assert normalize_surname("muster") == "MUSTER"


def test_normalize_givenname_ucwords_only_splits_on_spaces():
    # Mirrors PHP's ucwords(): splits on literal spaces only, unlike
    # Python's str.title() which also breaks on apostrophes/hyphens.
    assert normalize_givenname("mary jane") == "Mary Jane"
    assert normalize_givenname("o'brien") == "O'brien"
