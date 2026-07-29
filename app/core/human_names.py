def normalize_surname(value: str) -> str:
    return value.upper()


def normalize_givenname(value: str) -> str:
    """Mirrors Legacy's `ucwords()` mutator (HasHumanNames trait) -- PHP's
    ucwords() only splits on literal spaces (unlike Python's str.title(),
    which also breaks on apostrophes/hyphens), and leaves the rest of each
    word's casing untouched. Shared by User (auth_service.py) and Artist
    (artist_service.py) -- both mirror the same Legacy trait."""
    return " ".join(word[:1].upper() + word[1:] for word in value.split(" "))
