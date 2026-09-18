def normalize_surname(value: str) -> str:
    return value.upper()


def normalize_givenname(value: str) -> str:
    """Capitalize the first letter of each space-separated word. Unlike
    Python's str.title() (which also breaks on apostrophes/hyphens), only
    literal spaces split words, and the rest of each word's casing is left
    untouched. Shared by User (auth_service.py) and Artist
    (artist_service.py)."""
    return " ".join(word[:1].upper() + word[1:] for word in value.split(" "))


def label_for_name(surname: str, givenname: str | None) -> str:
    """Display name as "SURNAME, Givenname" -- same format as
    artist_service.label_for(), but taking plain fields instead of an Artist
    instance so it works for User too (booking_service needs a display name
    for both Artists (conductors) and Users (cast members))."""
    if not givenname:
        return surname
    return f"{surname}, {givenname}"
