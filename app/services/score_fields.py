"""Field-metadata registry for the Score (Notenarchiv) domain -- the single
source of truth for label/type/length/required/allowed-values per field.
Deliberately its own module (no
dependency on `app.schemas.score` or `app.services.score_service`): both
of those import FROM here (schemas.score references `.length`/`.values`
directly in its `Field()` declarations, score_service exposes this
registry as the `GET /scores/fields-config` response) -- putting the
registry in either of them would create a circular import.

Field shapes:
- "text"/"textarea": free text, `length` is the maximum length.
- "select": `values` is the exact allowed-value list. Optional selects
  start with a leading "" entry, the blank option (submitted as an empty
  string and normalized to None by the request schema). Required selects
  (like "inhalt") have no blank entry: leaving one unchosen is rejected.
- "number": every number field is required UNLESS explicitly marked
  nullable (only geboren/gestorben/jahr), which makes those three
  practically optional. `required=False` here reflects that practical
  behavior.
"""

from dataclasses import dataclass
from typing import Literal

ScoreFieldKind = Literal["text", "textarea", "select", "number"]


@dataclass(frozen=True)
class ScoreFieldSpec:
    label: str | None
    kind: ScoreFieldKind
    length: int | None = None
    required: bool = False
    values: tuple[str, ...] | None = None


_ART_VALUES: tuple[str, ...] = ("", "Original", "Kopie", "Original/Kopie")

# Part-type holdings section: 11 groups have verl(ag)/art/zust(and)/
# anz(ahl); "orch" alone only has the first three (no quantity column at
# all -- "orgel" DOES have one).
_PART_GROUPS_WITH_COUNT: tuple[str, ...] = (
    "part1",
    "part2",
    "klausz1",
    "klausz2",
    "chorpart1",
    "chorpart2",
    "stsopr",
    "stalt",
    "stten",
    "stbass",
    "orgel",
)
_PART_GROUPS_WITHOUT_COUNT: tuple[str, ...] = ("orch",)

# Instrumentation headcounts -- label only (no length/values).
_INSTRUMENT_LABELS: tuple[tuple[str, str], ...] = (
    ("violine1", "Violine 1"),
    ("violine2", "Violine 2"),
    ("viola", "Viola"),
    ("cello", "Cello"),
    ("contrabass", "Contrabass"),
    ("floete1", "Flöte 1"),
    ("floete2", "Flöte 2"),
    ("floete3", "Flöte 3"),
    ("oboe1", "Oboe 1"),
    ("oboe2", "Oboe 2"),
    ("klarinette1", "Klarinette 1"),
    ("klarinette2", "Klarinette 2"),
    ("fagott1", "Fagott 1"),
    ("fagott2", "Fagott 2"),
    ("kontrafagott", "Kontrafagott"),
    ("trombalt", "Altposaune"),
    ("trombten", "Tenorposaune"),
    ("trombbass", "Bassposaune"),
    ("corno1", "Horn 1"),
    ("corno2", "Horn 2"),
    ("trompete1", "Trompete 1"),
    ("trompete2", "Trompete 2"),
    ("trompete3", "Trompete 3"),
    ("pauke", "Pauke"),
)


def _part_group_fields(name: str, *, has_count: bool) -> dict[str, ScoreFieldSpec]:
    fields: dict[str, ScoreFieldSpec] = {
        f"{name}verl": ScoreFieldSpec(label=None, kind="text", length=64),
        f"{name}art": ScoreFieldSpec(label=None, kind="select", values=_ART_VALUES),
        f"{name}zust": ScoreFieldSpec(label=None, kind="text", length=8),
    }
    if has_count:
        fields[f"{name}anz"] = ScoreFieldSpec(label=None, kind="number", required=True)
    return fields


def _build_score_fields() -> dict[str, ScoreFieldSpec]:
    fields: dict[str, ScoreFieldSpec] = {
        # -- Fundort (physical location) --
        "kasten": ScoreFieldSpec("Kasten", "text", length=2, required=True),
        "boxnr": ScoreFieldSpec("Boxnummer", "text", length=16, required=True),
        "auch": ScoreFieldSpec("sieh auch Box/Mappe", "text", length=32),
        "inhalt": ScoreFieldSpec(
            "Inhalt",
            "select",
            required=True,
            values=(
                "Orchestermaterial",
                "Chormaterial",
                "Orch-/Chormaterial",
                "Klavierauszug",
                "Orgelauszug",
                "Partitur",
                "Singstimme",
            ),
        ),
        # -- Werk identification --
        "surname": ScoreFieldSpec("Nachname", "text", length=30),
        "givenname": ScoreFieldSpec("Vorname", "text", length=30),
        "geboren": ScoreFieldSpec("Geboren", "number"),
        "gestorben": ScoreFieldSpec("Gestorben", "number"),
        "werk": ScoreFieldSpec("Werk", "text", length=75, required=True),
        "teil": ScoreFieldSpec("Werkteil", "text", length=55),
        "sparte": ScoreFieldSpec(
            "Sparte",
            "select",
            values=(
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
            ),
        ),
        "verz": ScoreFieldSpec("Werkeverzeichnis/Mappe", "text", length=32),
        "jahr": ScoreFieldSpec("Jahr", "number"),
        # -- Remarks --
        "bemerkung": ScoreFieldSpec("Bemerkung", "textarea", length=256),
        "zusatznoten": ScoreFieldSpec("Zusatznoten", "textarea", length=256),
    }

    for name in _PART_GROUPS_WITH_COUNT:
        fields.update(_part_group_fields(name, has_count=True))
    for name in _PART_GROUPS_WITHOUT_COUNT:
        fields.update(_part_group_fields(name, has_count=False))

    for name, label in _INSTRUMENT_LABELS:
        fields[name] = ScoreFieldSpec(label, "number", required=True)

    for index in range(1, 5):
        fields[f"soinstr{index}art"] = ScoreFieldSpec(
            f"Name Sonderinstrument {index}", "text", length=32
        )
        fields[f"soinstr{index}anz"] = ScoreFieldSpec(
            f"Anzahl Sonderinstrument {index}", "number", required=True
        )

    return fields


SCORE_FIELDS: dict[str, ScoreFieldSpec] = _build_score_fields()
