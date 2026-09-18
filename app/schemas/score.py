import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import BlankToNone, OptionalText, StrictInputModel
from app.services.score_fields import SCORE_FIELDS

# Shared by all 12 "*art" (Original/Kopie/Original-Kopie) fields -- always
# optional: the form's blank option is submitted as "" and normalized to
# None.
_ArtValue = Literal["Original", "Kopie", "Original/Kopie"]
_OptionalArt = Annotated[_ArtValue | None, BlankToNone]

_SparteValue = Literal[
    "Advent/Weihnacht",
    "Bundeshymne",
    "Chor",
    "Lied",
    "Messe",
    "Oratorium",
    "Orch/Harfe",
    "Orch/Orgel",
    "Orch/Sakral",
    "Orch/Sol/Chor",
    "Orchester",
    "Passion",
    "Sakral",
    "Sakral/Solo",
    "Symphonie",
    "Volkslied",
]
# "sparte" is optional, like the "*art" fields above.
_OptionalSparte = Annotated[_SparteValue | None, BlankToNone]

# "inhalt" is REQUIRED: unlike the optional selects above it has no blank
# option, so an empty submission is rejected outright.
_InhaltValue = Literal[
    "Orchestermaterial",
    "Chormaterial",
    "Orch-/Chormaterial",
    "Klavierauszug",
    "Orgelauszug",
    "Partitur",
    "Singstimme",
]


class ScoreFieldConfig(BaseModel):
    """Wire form of one `score_fields.SCORE_FIELDS` entry, served via
    GET /scores/fields-config -- static, identical for every score, so the
    frontend fetches it once rather than on every create/edit/show call."""

    label: str | None
    kind: Literal["text", "textarea", "select", "number"]
    length: int | None
    required: bool
    values: list[str] | None


class ScoreRequest(StrictInputModel):
    """All 94 score card fields. The form always submits the full card, so
    every field must be present in the payload. Blank optional text/select
    values (submitted as "") are normalized to None and stored as NULL;
    numbers default to 0 in the form, including the optional
    geboren/gestorben/jahr. The service layer coalesces NULL back to "" / 0
    on read (see score_service.py), so Optional never needs to cross the
    response boundary."""

    # -- Fundort (physical location) --
    kasten: str = Field(min_length=1, max_length=SCORE_FIELDS["kasten"].length)
    boxnr: str = Field(min_length=1, max_length=SCORE_FIELDS["boxnr"].length)
    auch: OptionalText = Field(max_length=SCORE_FIELDS["auch"].length)
    inhalt: _InhaltValue

    # -- Werk identification --
    surname: OptionalText = Field(max_length=SCORE_FIELDS["surname"].length)
    givenname: OptionalText = Field(max_length=SCORE_FIELDS["givenname"].length)
    geboren: int = Field(ge=0, le=9999)
    gestorben: int = Field(ge=0, le=9999)
    werk: str = Field(min_length=1, max_length=SCORE_FIELDS["werk"].length)
    teil: OptionalText = Field(max_length=SCORE_FIELDS["teil"].length)
    sparte: _OptionalSparte
    verz: OptionalText = Field(max_length=SCORE_FIELDS["verz"].length)
    jahr: int = Field(ge=0, le=9999)

    # -- Holdings: Partitur 1/2 --
    part1verl: OptionalText = Field(max_length=SCORE_FIELDS["part1verl"].length)
    part1art: _OptionalArt
    part1zust: OptionalText = Field(max_length=SCORE_FIELDS["part1zust"].length)
    part1anz: int = Field(ge=0, le=9999)
    part2verl: OptionalText = Field(max_length=SCORE_FIELDS["part2verl"].length)
    part2art: _OptionalArt
    part2zust: OptionalText = Field(max_length=SCORE_FIELDS["part2zust"].length)
    part2anz: int = Field(ge=0, le=9999)

    # -- Holdings: Klavierauszug 1/2 --
    klausz1verl: OptionalText = Field(max_length=SCORE_FIELDS["klausz1verl"].length)
    klausz1art: _OptionalArt
    klausz1zust: OptionalText = Field(max_length=SCORE_FIELDS["klausz1zust"].length)
    klausz1anz: int = Field(ge=0, le=9999)
    klausz2verl: OptionalText = Field(max_length=SCORE_FIELDS["klausz2verl"].length)
    klausz2art: _OptionalArt
    klausz2zust: OptionalText = Field(max_length=SCORE_FIELDS["klausz2zust"].length)
    klausz2anz: int = Field(ge=0, le=9999)

    # -- Holdings: Chorpartitur 1/2 --
    chorpart1verl: OptionalText = Field(max_length=SCORE_FIELDS["chorpart1verl"].length)
    chorpart1art: _OptionalArt
    chorpart1zust: OptionalText = Field(max_length=SCORE_FIELDS["chorpart1zust"].length)
    chorpart1anz: int = Field(ge=0, le=9999)
    chorpart2verl: OptionalText = Field(max_length=SCORE_FIELDS["chorpart2verl"].length)
    chorpart2art: _OptionalArt
    chorpart2zust: OptionalText = Field(max_length=SCORE_FIELDS["chorpart2zust"].length)
    chorpart2anz: int = Field(ge=0, le=9999)

    # -- Holdings: Stimmen (Sopran/Alt/Tenor/Bass) --
    stsoprverl: OptionalText = Field(max_length=SCORE_FIELDS["stsoprverl"].length)
    stsoprart: _OptionalArt
    stsoprzust: OptionalText = Field(max_length=SCORE_FIELDS["stsoprzust"].length)
    stsopranz: int = Field(ge=0, le=9999)
    staltverl: OptionalText = Field(max_length=SCORE_FIELDS["staltverl"].length)
    staltart: _OptionalArt
    staltzust: OptionalText = Field(max_length=SCORE_FIELDS["staltzust"].length)
    staltanz: int = Field(ge=0, le=9999)
    sttenverl: OptionalText = Field(max_length=SCORE_FIELDS["sttenverl"].length)
    sttenart: _OptionalArt
    sttenzust: OptionalText = Field(max_length=SCORE_FIELDS["sttenzust"].length)
    sttenanz: int = Field(ge=0, le=9999)
    stbassverl: OptionalText = Field(max_length=SCORE_FIELDS["stbassverl"].length)
    stbassart: _OptionalArt
    stbasszust: OptionalText = Field(max_length=SCORE_FIELDS["stbasszust"].length)
    stbassanz: int = Field(ge=0, le=9999)

    # -- Holdings: Orgel/Orchester ("orch" alone has no "anz" column) --
    orgelverl: OptionalText = Field(max_length=SCORE_FIELDS["orgelverl"].length)
    orgelart: _OptionalArt
    orgelzust: OptionalText = Field(max_length=SCORE_FIELDS["orgelzust"].length)
    orgelanz: int = Field(ge=0, le=9999)
    orchverl: OptionalText = Field(max_length=SCORE_FIELDS["orchverl"].length)
    orchart: _OptionalArt
    orchzust: OptionalText = Field(max_length=SCORE_FIELDS["orchzust"].length)

    # -- Instrumentation headcounts --
    violine1: int = Field(ge=0, le=9999)
    violine2: int = Field(ge=0, le=9999)
    viola: int = Field(ge=0, le=9999)
    cello: int = Field(ge=0, le=9999)
    contrabass: int = Field(ge=0, le=9999)
    floete1: int = Field(ge=0, le=9999)
    floete2: int = Field(ge=0, le=9999)
    floete3: int = Field(ge=0, le=9999)
    oboe1: int = Field(ge=0, le=9999)
    oboe2: int = Field(ge=0, le=9999)
    klarinette1: int = Field(ge=0, le=9999)
    klarinette2: int = Field(ge=0, le=9999)
    fagott1: int = Field(ge=0, le=9999)
    fagott2: int = Field(ge=0, le=9999)
    kontrafagott: int = Field(ge=0, le=9999)
    trombalt: int = Field(ge=0, le=9999)
    trombten: int = Field(ge=0, le=9999)
    trombbass: int = Field(ge=0, le=9999)
    corno1: int = Field(ge=0, le=9999)
    corno2: int = Field(ge=0, le=9999)
    trompete1: int = Field(ge=0, le=9999)
    trompete2: int = Field(ge=0, le=9999)
    trompete3: int = Field(ge=0, le=9999)
    pauke: int = Field(ge=0, le=9999)

    # -- Special/guest instrument slots --
    soinstr1art: OptionalText = Field(max_length=SCORE_FIELDS["soinstr1art"].length)
    soinstr1anz: int = Field(ge=0, le=9999)
    soinstr2art: OptionalText = Field(max_length=SCORE_FIELDS["soinstr2art"].length)
    soinstr2anz: int = Field(ge=0, le=9999)
    soinstr3art: OptionalText = Field(max_length=SCORE_FIELDS["soinstr3art"].length)
    soinstr3anz: int = Field(ge=0, le=9999)
    soinstr4art: OptionalText = Field(max_length=SCORE_FIELDS["soinstr4art"].length)
    soinstr4anz: int = Field(ge=0, le=9999)

    # -- Remarks --
    bemerkung: OptionalText = Field(max_length=SCORE_FIELDS["bemerkung"].length)
    zusatznoten: OptionalText = Field(max_length=SCORE_FIELDS["zusatznoten"].length)


class ScoreResponse(BaseModel):
    id: uuid.UUID
    created_at: UtcDatetime | None
    updated_at: UtcDatetime | None
    fields: dict[str, str | int]


class ScoreSearchResult(BaseModel):
    id: uuid.UUID
    label: str
