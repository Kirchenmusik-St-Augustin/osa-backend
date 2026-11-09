import uuid
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)


class StrictInputModel(BaseModel):
    """Base of every request body: unknown fields are rejected and values are
    never coerced to the declared type (a string is not accepted for an int)."""

    model_config = ConfigDict(extra="forbid", strict=True)


# Pydantic's model-level strict=True rejects a UUID-formatted STRING for a
# plain `uuid.UUID` field -- JSON has no native UUID type, so every real
# HTTP request body carries a string here, and strict mode's Python-dict
# validation path (which is what FastAPI actually uses for JSON request
# bodies) doesn't auto-parse it the way non-strict mode would. A per-field
# `strict=False` override is the narrow, documented escape hatch for
# exactly this case -- it does NOT loosen anything else (extra="forbid"
# and every other field's strictness stay untouched). Same technique as
# app.schemas.performance's `_LenientDatetime`, shared here because every
# id field across the whole schema layer needs it.
LenientUuid = Annotated[uuid.UUID, Field(strict=False)]


class IdNameOutput(BaseModel):
    """A reference to a catalogue entry or a person: the id and the name to
    show for it."""

    id: uuid.UUID
    name: str


class IdLabelOutput(BaseModel):
    """One hit of a search: the id and the text to show for it."""

    id: uuid.UUID
    label: str


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


# An optional value that forms submit as an empty (or whitespace-only) string
# when left blank: normalized to None at the schema boundary, so the service
# and database layers only ever see a real value or None -- never "" as a
# stand-in for "no value". Combine with a type, e.g.
# `Annotated[Literal["a", "b"] | None, BlankToNone]`.
BlankToNone = BeforeValidator(_blank_to_none)

# The default bound keeps a free-text field from taking a request body's worth
# of text. The bound sits on the string branch of the union: on the union itself
# it would be applied to None as well. A field with its own
# `Field(max_length=...)` keeps both limits, so only a smaller limit takes
# effect there.
OPTIONAL_TEXT_MAX_LENGTH = 2000
OptionalText = Annotated[
    Annotated[str, Field(max_length=OPTIONAL_TEXT_MAX_LENGTH)] | None, BlankToNone
]


def _normalize_email(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


# An e-mail address as it is stored and compared: lower case (the database
# enforces it with a CHECK constraint; EmailStr itself removes surrounding
# blanks, but only lower-cases the domain), and short enough to be saved from
# the profile form later.
EMAIL_MAX_LENGTH = 190
NormalizedEmail = Annotated[
    EmailStr, BeforeValidator(_normalize_email), Field(max_length=EMAIL_MAX_LENGTH)
]

# A surname or given name: surrounding whitespace is removed before the length
# is checked, so " Bach " and "Bach" are one name and a blank name is refused.
# The minimum of one character keeps short real names (Li, Wu, Ng, "J.") valid.
# A field type instead of a model-wide setting, because passwords must never be
# altered by the schema.
PersonName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
]

# The title of an ordinarium or proprium work: stripped like a person name, so
# "Ave Maria" and "Ave Maria " are one title for the same composer.
WorkName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=60)
]

# Largest number of entries a request list may carry: the catalogue of
# instruments, voices, choir jobs and roles and the cast of one performance are
# far smaller, so a bigger list only costs the service time per entry.
MAX_CATALOGUE_ENTRIES = 200
MAX_RECIPIENTS = 500
MAX_PROPRIUM_ENTRIES = 50
MAX_REHEARSALS = 20

# The text of a message to the cast: a message of blanks is no message.
MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]

# A message typed into a free-text box: a message of blanks is no message.
SupportMessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)
]
