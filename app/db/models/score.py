from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

# Shared by every "Original/Kopie/Original-Kopie" condition column below --
# 1:1 the CHECK constraint on all 12 `*art` columns in the real schema.
_ART_CHECK = "IN ('Original', 'Kopie', 'Original/Kopie')"


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
    delete endpoint or service function at all, not even a stub."""

    __tablename__ = "scores"
    __table_args__ = (
        CheckConstraint(
            "inhalt IN ('Orchestermaterial', 'Chormaterial', "
            "'Orch-/Chormaterial', 'Klavierauszug', 'Orgelauszug', "
            "'Partitur', 'Singstimme')"
        ),
        CheckConstraint(
            "sparte IN ('Advent/Weihnacht', 'Bundeshymne', 'Chor', 'Lied', "
            "'Messe', 'Oratorium', 'Orch/Harfe', 'Orch/Orgel', "
            "'Orch/Sakral', 'Orch/Sol/Chor', 'Orchester', 'Passion', "
            "'Sakral', 'Sakral/Solo', 'Symphonie', 'Volkslied')"
        ),
        CheckConstraint(f"part1art {_ART_CHECK}"),
        CheckConstraint(f"part2art {_ART_CHECK}"),
        CheckConstraint(f"klausz1art {_ART_CHECK}"),
        CheckConstraint(f"klausz2art {_ART_CHECK}"),
        CheckConstraint(f"chorpart1art {_ART_CHECK}"),
        CheckConstraint(f"chorpart2art {_ART_CHECK}"),
        CheckConstraint(f"stsoprart {_ART_CHECK}"),
        CheckConstraint(f"staltart {_ART_CHECK}"),
        CheckConstraint(f"sttenart {_ART_CHECK}"),
        CheckConstraint(f"stbassart {_ART_CHECK}"),
        CheckConstraint(f"orgelart {_ART_CHECK}"),
        CheckConstraint(f"orchart {_ART_CHECK}"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # -- Werk identification --
    kasten: Mapped[str | None] = mapped_column()
    boxnr: Mapped[str | None] = mapped_column()
    auch: Mapped[str | None] = mapped_column()
    inhalt: Mapped[str | None] = mapped_column()
    surname: Mapped[str | None] = mapped_column()
    givenname: Mapped[str | None] = mapped_column()
    geboren: Mapped[int | None] = mapped_column()
    gestorben: Mapped[int | None] = mapped_column()
    werk: Mapped[str | None] = mapped_column()
    teil: Mapped[str | None] = mapped_column()
    sparte: Mapped[str | None] = mapped_column()
    verz: Mapped[str | None] = mapped_column()
    jahr: Mapped[int | None] = mapped_column()

    # -- Holdings per part-type: verl(ag)/art/zust(and)/anz(ahl). "orch"
    # is the ONLY group with no `anz` column at all -- "orgel" does have
    # one, confirmed by the real schema (a first read of it mistakenly
    # assumed both lacked it; caught live via Playwright, since Legacy's
    # own Score/Show.vue genuinely displays an Orgel-Stimme "Anzahl" cell).
    part1verl: Mapped[str | None] = mapped_column()
    part1art: Mapped[str | None] = mapped_column()
    part1zust: Mapped[str | None] = mapped_column()
    part1anz: Mapped[int] = mapped_column(default=0)
    part2verl: Mapped[str | None] = mapped_column()
    part2art: Mapped[str | None] = mapped_column()
    part2zust: Mapped[str | None] = mapped_column()
    part2anz: Mapped[int] = mapped_column(default=0)
    klausz1verl: Mapped[str | None] = mapped_column()
    klausz1art: Mapped[str | None] = mapped_column()
    klausz1zust: Mapped[str | None] = mapped_column()
    klausz1anz: Mapped[int] = mapped_column(default=0)
    klausz2verl: Mapped[str | None] = mapped_column()
    klausz2art: Mapped[str | None] = mapped_column()
    klausz2zust: Mapped[str | None] = mapped_column()
    klausz2anz: Mapped[int] = mapped_column(default=0)
    chorpart1verl: Mapped[str | None] = mapped_column()
    chorpart1art: Mapped[str | None] = mapped_column()
    chorpart1zust: Mapped[str | None] = mapped_column()
    chorpart1anz: Mapped[int] = mapped_column(default=0)
    chorpart2verl: Mapped[str | None] = mapped_column()
    chorpart2art: Mapped[str | None] = mapped_column()
    chorpart2zust: Mapped[str | None] = mapped_column()
    chorpart2anz: Mapped[int] = mapped_column(default=0)
    stsoprverl: Mapped[str | None] = mapped_column()
    stsoprart: Mapped[str | None] = mapped_column()
    stsoprzust: Mapped[str | None] = mapped_column()
    stsopranz: Mapped[int] = mapped_column(default=0)
    staltverl: Mapped[str | None] = mapped_column()
    staltart: Mapped[str | None] = mapped_column()
    staltzust: Mapped[str | None] = mapped_column()
    staltanz: Mapped[int] = mapped_column(default=0)
    sttenverl: Mapped[str | None] = mapped_column()
    sttenart: Mapped[str | None] = mapped_column()
    sttenzust: Mapped[str | None] = mapped_column()
    sttenanz: Mapped[int] = mapped_column(default=0)
    stbassverl: Mapped[str | None] = mapped_column()
    stbassart: Mapped[str | None] = mapped_column()
    stbasszust: Mapped[str | None] = mapped_column()
    stbassanz: Mapped[int] = mapped_column(default=0)
    orgelverl: Mapped[str | None] = mapped_column()
    orgelart: Mapped[str | None] = mapped_column()
    orgelzust: Mapped[str | None] = mapped_column()
    orgelanz: Mapped[int] = mapped_column(default=0)
    orchverl: Mapped[str | None] = mapped_column()
    orchart: Mapped[str | None] = mapped_column()
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

    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
