from typing import Literal

from pydantic import BaseModel, Field

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import StrictInputModel
from app.services.score_fields import SCORE_FIELDS

# Shared by all 12 "*art" (Original/Kopie/Original-Kopie) fields -- always
# optional, so the blank placeholder stays a real, reachable option here
# (unlike the required selects below).
_ArtValue = Literal["", "Original", "Kopie", "Original/Kopie"]

# "sparte" is optional -- blank placeholder stays reachable.
_SparteValue = Literal[
    "",
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

# "inhalt" is REQUIRED -- Legacy's own config still lists a leading ""
# among its allowed `values` (kept in SCORE_FIELDS for the fields-config
# wire format, i.e. the rendered <select>'s placeholder option), but
# Laravel's `required` rule rejects an actually-empty submission before
# the `in:` rule is ever reached, so "" is practically unreachable here.
# Excluding it from this Literal enforces that same practical outcome.
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
    """All 94 Score::$fields values. Every field always carries a concrete
    value (never None) -- 1:1 how Legacy's own form always submits a full
    payload (`setDefaults()` seeds "" for text/select, 0 for every number
    including the "nullable" geboren/gestorben/jahr, which Legacy's own
    create form also defaults to 0, never blank). NULL only ever appears
    at the DB layer for pre-existing rows; the service layer coalesces it
    to "" / 0 on read (see score_service.py), so Optional never needs to
    cross this API boundary at all."""

    # -- Fundort (physical location) --
    kasten: str = Field(min_length=1, max_length=SCORE_FIELDS["kasten"].length)
    boxnr: str = Field(min_length=1, max_length=SCORE_FIELDS["boxnr"].length)
    auch: str = Field(max_length=SCORE_FIELDS["auch"].length)
    inhalt: _InhaltValue

    # -- Werk identification --
    surname: str = Field(max_length=SCORE_FIELDS["surname"].length)
    givenname: str = Field(max_length=SCORE_FIELDS["givenname"].length)
    geboren: int = Field(ge=0, le=9999)
    gestorben: int = Field(ge=0, le=9999)
    werk: str = Field(min_length=1, max_length=SCORE_FIELDS["werk"].length)
    teil: str = Field(max_length=SCORE_FIELDS["teil"].length)
    sparte: _SparteValue
    verz: str = Field(max_length=SCORE_FIELDS["verz"].length)
    jahr: int = Field(ge=0, le=9999)

    # -- Holdings: Partitur 1/2 --
    part1verl: str = Field(max_length=SCORE_FIELDS["part1verl"].length)
    part1art: _ArtValue
    part1zust: str = Field(max_length=SCORE_FIELDS["part1zust"].length)
    part1anz: int = Field(ge=0, le=9999)
    part2verl: str = Field(max_length=SCORE_FIELDS["part2verl"].length)
    part2art: _ArtValue
    part2zust: str = Field(max_length=SCORE_FIELDS["part2zust"].length)
    part2anz: int = Field(ge=0, le=9999)

    # -- Holdings: Klavierauszug 1/2 --
    klausz1verl: str = Field(max_length=SCORE_FIELDS["klausz1verl"].length)
    klausz1art: _ArtValue
    klausz1zust: str = Field(max_length=SCORE_FIELDS["klausz1zust"].length)
    klausz1anz: int = Field(ge=0, le=9999)
    klausz2verl: str = Field(max_length=SCORE_FIELDS["klausz2verl"].length)
    klausz2art: _ArtValue
    klausz2zust: str = Field(max_length=SCORE_FIELDS["klausz2zust"].length)
    klausz2anz: int = Field(ge=0, le=9999)

    # -- Holdings: Chorpartitur 1/2 --
    chorpart1verl: str = Field(max_length=SCORE_FIELDS["chorpart1verl"].length)
    chorpart1art: _ArtValue
    chorpart1zust: str = Field(max_length=SCORE_FIELDS["chorpart1zust"].length)
    chorpart1anz: int = Field(ge=0, le=9999)
    chorpart2verl: str = Field(max_length=SCORE_FIELDS["chorpart2verl"].length)
    chorpart2art: _ArtValue
    chorpart2zust: str = Field(max_length=SCORE_FIELDS["chorpart2zust"].length)
    chorpart2anz: int = Field(ge=0, le=9999)

    # -- Holdings: Stimmen (Sopran/Alt/Tenor/Bass) --
    stsoprverl: str = Field(max_length=SCORE_FIELDS["stsoprverl"].length)
    stsoprart: _ArtValue
    stsoprzust: str = Field(max_length=SCORE_FIELDS["stsoprzust"].length)
    stsopranz: int = Field(ge=0, le=9999)
    staltverl: str = Field(max_length=SCORE_FIELDS["staltverl"].length)
    staltart: _ArtValue
    staltzust: str = Field(max_length=SCORE_FIELDS["staltzust"].length)
    staltanz: int = Field(ge=0, le=9999)
    sttenverl: str = Field(max_length=SCORE_FIELDS["sttenverl"].length)
    sttenart: _ArtValue
    sttenzust: str = Field(max_length=SCORE_FIELDS["sttenzust"].length)
    sttenanz: int = Field(ge=0, le=9999)
    stbassverl: str = Field(max_length=SCORE_FIELDS["stbassverl"].length)
    stbassart: _ArtValue
    stbasszust: str = Field(max_length=SCORE_FIELDS["stbasszust"].length)
    stbassanz: int = Field(ge=0, le=9999)

    # -- Holdings: Orgel/Orchester ("orch" alone has no "anz" column) --
    orgelverl: str = Field(max_length=SCORE_FIELDS["orgelverl"].length)
    orgelart: _ArtValue
    orgelzust: str = Field(max_length=SCORE_FIELDS["orgelzust"].length)
    orgelanz: int = Field(ge=0, le=9999)
    orchverl: str = Field(max_length=SCORE_FIELDS["orchverl"].length)
    orchart: _ArtValue
    orchzust: str = Field(max_length=SCORE_FIELDS["orchzust"].length)

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
    soinstr1art: str = Field(max_length=SCORE_FIELDS["soinstr1art"].length)
    soinstr1anz: int = Field(ge=0, le=9999)
    soinstr2art: str = Field(max_length=SCORE_FIELDS["soinstr2art"].length)
    soinstr2anz: int = Field(ge=0, le=9999)
    soinstr3art: str = Field(max_length=SCORE_FIELDS["soinstr3art"].length)
    soinstr3anz: int = Field(ge=0, le=9999)
    soinstr4art: str = Field(max_length=SCORE_FIELDS["soinstr4art"].length)
    soinstr4anz: int = Field(ge=0, le=9999)

    # -- Remarks --
    bemerkung: str = Field(max_length=SCORE_FIELDS["bemerkung"].length)
    zusatznoten: str = Field(max_length=SCORE_FIELDS["zusatznoten"].length)


class ScoreResponse(BaseModel):
    id: int
    created_at: UtcDatetime | None
    updated_at: UtcDatetime | None
    fields: dict[str, str | int]


class ScoreSearchResult(BaseModel):
    id: int
    label: str
