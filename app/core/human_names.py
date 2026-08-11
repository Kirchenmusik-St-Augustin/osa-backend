def normalize_surname(value: str) -> str:
    return value.upper()


def normalize_givenname(value: str) -> str:
    """Mirrors Legacy's `ucwords()` mutator (HasHumanNames trait) -- PHP's
    ucwords() only splits on literal spaces (unlike Python's str.title(),
    which also breaks on apostrophes/hyphens), and leaves the rest of each
    word's casing untouched. Shared by User (auth_service.py) and Artist
    (artist_service.py) -- both mirror the same Legacy trait."""
    return " ".join(word[:1].upper() + word[1:] for word in value.split(" "))


def label_for_name(surname: str, givenname: str | None) -> str:
    """Mirrors Legacy's `HasHumanNames::name()` virtual attribute
    ("SURNAME, Givenname") -- 1:1 artist_service.label_for(), but taking
    plain fields instead of an Artist instance so it works for User too
    (booking_service needs a display name for both Artists (conductors)
    and Users (cast members), see project_osa_migration_plan memory,
    Schritt 6)."""
    if not givenname:
        return surname
    return f"{surname}, {givenname}"
