from datetime import datetime

from sqlalchemy import DateTime, Enum, FetchedValue, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

# Shared by all 12 "Original/Kopie/Original-Kopie" condition columns below
# -- native Postgres ENUM as of the enum-hardening slice (2026-09),
# replacing what used to be an identical CheckConstraint string duplicated
# 12 times. Deliberately bare string literals, not a bound Python
# enum.Enum class -- see app.db.models.position_type_enum's docstring for
# why (avoids the values_callable footgun). soinstr1art..soinstr4art
# deliberately do NOT use this type: despite the "art" name, they have no
# CheckConstraint even before this slice (confirmed free-text fields, see
# app.services.score_fields) and stay plain varchar.
_ART_ENUM = Enum("Original", "Kopie", "Original/Kopie", name="score_art")

_INHALT_ENUM = Enum(
    "Orchestermaterial",
    "Chormaterial",
    "Orch-/Chormaterial",
    "Klavierauszug",
    "Orgelauszug",
    "Partitur",
    "Singstimme",
    name="score_inhalt",
)

_SPARTE_ENUM = Enum(
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
    name="score_sparte",
)


class Score(Base):
    """Mirrors legacy `scores` exactly (Phase 1) -- a physical sheet-music
    archive card catalog (NOT a digital/PDF archive: no file storage
    anywhere in this domain), one row per work. Legacy's own `Score::
    $fields` config array (see app.services.score_service.SCORE_FIELDS,
    the single source of truth reused for both validation and the
    frontend's field metadata) is the authoritative field list -- this
    model just mirrors the raw column shapes. No `has_dependencies`/delete
    concept: Legacy's own route registration excludes `destroy` entirely
    (`Route::resource(...)->except(['destroy'])`, its controller method is
    dead code, "as an archive should archive things") -- this port has no
    delete endpoint or service function at all, not even a stub.

    `inhalt`/`sparte`/the 12 `*art` columns are native Postgres ENUMs as
    of the enum-hardening slice (2026-09), replacing what used to be 14
    CheckConstraints -- `Mapped[str]` is unchanged, every existing string
    comparison/lookup on these columns keeps working.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(primary_key=True)

    # -- Werk identification --
    kasten: Mapped[str | None] = mapped_column()
    boxnr: Mapped[str | None] = mapped_column()
    auch: Mapped[str | None] = mapped_column()
    inhalt: Mapped[str | None] = mapped_column(_INHALT_ENUM)
    surname: Mapped[str | None] = mapped_column()
    givenname: Mapped[str | None] = mapped_column()
    geboren: Mapped[int | None] = mapped_column()
    gestorben: Mapped[int | None] = mapped_column()
    werk: Mapped[str | None] = mapped_column()
    teil: Mapped[str | None] = mapped_column()
    sparte: Mapped[str | None] = mapped_column(_SPARTE_ENUM)
    verz: Mapped[str | None] = mapped_column()
    jahr: Mapped[int | None] = mapped_column()

    # -- Holdings per part-type: verl(ag)/art/zust(and)/anz(ahl). "orch"
    # is the ONLY group with no `anz` column at all -- "orgel" does have
    # one, confirmed by the real schema (a first read of it mistakenly
    # assumed both lacked it; caught live via Playwright, since Legacy's
    # own Score/Show.vue genuinely displays an Orgel-Stimme "Anzahl" cell).
    part1verl: Mapped[str | None] = mapped_column()
    part1art: Mapped[str | None] = mapped_column(_ART_ENUM)
    part1zust: Mapped[str | None] = mapped_column()
    part1anz: Mapped[int] = mapped_column(default=0)
    part2verl: Mapped[str | None] = mapped_column()
    part2art: Mapped[str | None] = mapped_column(_ART_ENUM)
    part2zust: Mapped[str | None] = mapped_column()
    part2anz: Mapped[int] = mapped_column(default=0)
    klausz1verl: Mapped[str | None] = mapped_column()
    klausz1art: Mapped[str | None] = mapped_column(_ART_ENUM)
    klausz1zust: Mapped[str | None] = mapped_column()
    klausz1anz: Mapped[int] = mapped_column(default=0)
    klausz2verl: Mapped[str | None] = mapped_column()
    klausz2art: Mapped[str | None] = mapped_column(_ART_ENUM)
    klausz2zust: Mapped[str | None] = mapped_column()
    klausz2anz: Mapped[int] = mapped_column(default=0)
    chorpart1verl: Mapped[str | None] = mapped_column()
    chorpart1art: Mapped[str | None] = mapped_column(_ART_ENUM)
    chorpart1zust: Mapped[str | None] = mapped_column()
    chorpart1anz: Mapped[int] = mapped_column(default=0)
    chorpart2verl: Mapped[str | None] = mapped_column()
    chorpart2art: Mapped[str | None] = mapped_column(_ART_ENUM)
    chorpart2zust: Mapped[str | None] = mapped_column()
    chorpart2anz: Mapped[int] = mapped_column(default=0)
    stsoprverl: Mapped[str | None] = mapped_column()
    stsoprart: Mapped[str | None] = mapped_column(_ART_ENUM)
    stsoprzust: Mapped[str | None] = mapped_column()
    stsopranz: Mapped[int] = mapped_column(default=0)
    staltverl: Mapped[str | None] = mapped_column()
    staltart: Mapped[str | None] = mapped_column(_ART_ENUM)
    staltzust: Mapped[str | None] = mapped_column()
    staltanz: Mapped[int] = mapped_column(default=0)
    sttenverl: Mapped[str | None] = mapped_column()
    sttenart: Mapped[str | None] = mapped_column(_ART_ENUM)
    sttenzust: Mapped[str | None] = mapped_column()
    sttenanz: Mapped[int] = mapped_column(default=0)
    stbassverl: Mapped[str | None] = mapped_column()
    stbassart: Mapped[str | None] = mapped_column(_ART_ENUM)
    stbasszust: Mapped[str | None] = mapped_column()
    stbassanz: Mapped[int] = mapped_column(default=0)
    orgelverl: Mapped[str | None] = mapped_column()
    orgelart: Mapped[str | None] = mapped_column(_ART_ENUM)
    orgelzust: Mapped[str | None] = mapped_column()
    orgelanz: Mapped[int] = mapped_column(default=0)
    orchverl: Mapped[str | None] = mapped_column()
    orchart: Mapped[str | None] = mapped_column(_ART_ENUM)
    orchzust: Mapped[str | None] = mapped_column()

    # -- Instrumentation headcounts --
    violine1: Mapped[int] = mapped_column(default=0)
    violine2: Mapped[int] = mapped_column(default=0)
    viola: Mapped[int] = mapped_column(default=0)
    cello: Mapped[int] = mapped_column(default=0)
    contrabass: Mapped[int] = mapped_column(default=0)
    floete1: Mapped[int] = mapped_column(default=0)
    floete2: Mapped[int] = mapped_column(default=0)
    floete3: Mapped[int] = mapped_column(default=0)
    oboe1: Mapped[int] = mapped_column(default=0)
    oboe2: Mapped[int] = mapped_column(default=0)
    klarinette1: Mapped[int] = mapped_column(default=0)
    klarinette2: Mapped[int] = mapped_column(default=0)
    fagott1: Mapped[int] = mapped_column(default=0)
    fagott2: Mapped[int] = mapped_column(default=0)
    kontrafagott: Mapped[int] = mapped_column(default=0)
    trombalt: Mapped[int] = mapped_column(default=0)
    trombten: Mapped[int] = mapped_column(default=0)
    trombbass: Mapped[int] = mapped_column(default=0)
    corno1: Mapped[int] = mapped_column(default=0)
    corno2: Mapped[int] = mapped_column(default=0)
    trompete1: Mapped[int] = mapped_column(default=0)
    trompete2: Mapped[int] = mapped_column(default=0)
    trompete3: Mapped[int] = mapped_column(default=0)
    pauke: Mapped[int] = mapped_column(default=0)

    # -- Special/guest instrument slots --
    soinstr1art: Mapped[str | None] = mapped_column()
    soinstr1anz: Mapped[int] = mapped_column(default=0)
    soinstr2art: Mapped[str | None] = mapped_column()
    soinstr2anz: Mapped[int] = mapped_column(default=0)
    soinstr3art: Mapped[str | None] = mapped_column()
    soinstr3anz: Mapped[int] = mapped_column(default=0)
    soinstr4art: Mapped[str | None] = mapped_column()
    soinstr4anz: Mapped[int] = mapped_column(default=0)

    # -- Remarks --
    bemerkung: Mapped[str | None] = mapped_column()
    zusatznoten: Mapped[str | None] = mapped_column()

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
