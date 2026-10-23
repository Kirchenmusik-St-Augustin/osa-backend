from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.human_names import label_for_name, normalize_givenname, normalize_surname
from app.db.models.score import Score
from app.schemas.base import IdLabelOutput
from app.schemas.score import ScoreFieldConfig, ScoreRequest, ScoreResponse
from app.schemas.score_fields import SCORE_FIELDS
from app.services.errors import NotFoundError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Sequence

    from sqlalchemy.orm import Session

    from app.schemas.score_fields import ScoreFieldSpec

_SEARCH_RESULT_LIMIT = 50


class ScoreNotFoundError(NotFoundError):
    """Raised when `score_id` doesn't exist."""


def get_fields_config() -> dict[str, ScoreFieldConfig]:
    """Static field metadata, served once and reused by the Search/Create/
    Edit/Show pages alike (see app.schemas.score.ScoreFieldConfig)."""
    return {
        name: ScoreFieldConfig(
            label=spec.label,
            kind=spec.kind,
            length=spec.length,
            required=spec.required,
            values=list(spec.values) if spec.values is not None else None,
        )
        for name, spec in SCORE_FIELDS.items()
    }


def get_defaults() -> dict[str, str | int | None]:
    """Initial form value per field: 0 for every required number field, ""
    for everything else -- for a select that is the blank "nothing chosen
    yet" state (optional selects offer it as a real blank option, required
    selects reject it on submit). geboren/gestorben/jahr are the only
    number fields that are genuinely optional (no meaningful year 0), so
    they default to None instead of 0."""
    return {
        name: _number_default(spec) if spec.kind == "number" else ""
        for name, spec in SCORE_FIELDS.items()
    }


def _number_default(spec: ScoreFieldSpec) -> int | None:
    return 0 if spec.required else None


def _field_value(score: Score, name: str, spec: ScoreFieldSpec) -> str | int | None:
    """Coalesces NULL (possible for pre-existing/imported rows) to "" for
    text fields and to 0 for required number fields -- Optional never
    needs to cross the API boundary for those (see ScoreRequest's
    docstring). geboren/gestorben/jahr are the exception: NULL stays NULL,
    since blank is a real state for those three, not a placeholder."""
    value = getattr(score, name)
    if spec.kind != "number":
        return value if value is not None else ""
    if value is not None:
        return value
    return 0 if spec.required else None


def _fields_dict(score: Score) -> dict[str, str | int | None]:
    """Reads all 94 field values off `score` (see `_field_value`)."""
    return {
        name: _field_value(score, name, spec) for name, spec in SCORE_FIELDS.items()
    }


def _normalized_name(value: str | None, normalize: Callable[[str], str]) -> str | None:
    return normalize(value) if value is not None else None


def _apply_fields(score: Score, data: ScoreRequest) -> None:
    payload = data.model_dump()
    for name in SCORE_FIELDS:
        if name in ("surname", "givenname"):
            continue  # normalized separately below
        setattr(score, name, payload[name])
    # Same name normalization as User/Artist (app.core.human_names).
    score.surname = _normalized_name(data.surname, normalize_surname)
    score.givenname = _normalized_name(data.givenname, normalize_givenname)


def _to_response(score: Score) -> ScoreResponse:
    return ScoreResponse(
        id=score.id,
        created_at=score.created_at,
        # updated_at is NULL until the row's first real UPDATE (the
        # set_updated_at() trigger doesn't fire on insert) -- created_at
        # is the meaningful fallback for a freshly created score.
        updated_at=score.updated_at or score.created_at,
        fields=_fields_dict(score),
    )


def _get_or_404(db: Session, score_id: uuid.UUID) -> Score:
    result = db.execute(select(Score).where(Score.id == score_id))
    score = result.scalar_one_or_none()
    if score is None:
        raise ScoreNotFoundError
    return score


def search_scores(db: Session, query: str) -> list[IdLabelOutput]:
    """Filtered in the database (not in memory). Every whitespace-separated
    word in `query` must appear somewhere in "surname givenname werk teil".
    `coalesce()` on every nullable column -- SQL `||` yields NULL if any
    operand is NULL."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return []

    combined = func.lower(
        func.coalesce(Score.surname, "")
        + " "
        + func.coalesce(Score.givenname, "")
        + " "
        + func.coalesce(Score.werk, "")
        + " "
        + func.coalesce(Score.teil, "")
    )
    stmt = (
        select(Score)
        .where(*[combined.contains(word, autoescape=True) for word in words])
        # werk, teil and id make the order of hits with the same composer
        # stable, so versions of one work keep their place between searches.
        .order_by(Score.surname, Score.werk, Score.teil, Score.id)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    scores = db.execute(stmt).scalars().all()
    return [
        IdLabelOutput(id=score.id, label=label)
        for score, label in zip(scores, _disambiguated_labels(scores), strict=True)
    ]


def _label_for_score(score: Score) -> str:
    name = label_for_name(score.surname or "", score.givenname)
    label = f"{name}: {score.werk or ''}"
    if score.teil:
        label += f" / {score.teil}"
    return label


def _catalogue_number(score: Score) -> str:
    return score.verz or ""


def _box(score: Score) -> str:
    return f"Box {score.boxnr}" if score.boxnr else ""


def _year(score: Score) -> str:
    return str(score.jahr) if score.jahr is not None else ""


def _genre(score: Score) -> str:
    return score.sparte or ""


def _entered_on(score: Score) -> str:
    return f"erfasst am {score.created_at:%d.%m.%Y}"


# What tells apart cards of the same work, in the order it is tried: the
# archive holds several versions of one work (catalogue number, box, year,
# genre differ), which would otherwise read identically in the hit list.
_DISAMBIGUATION_FIELDS: tuple[Callable[[Score], str], ...] = (
    _catalogue_number,
    _box,
    _year,
    _genre,
)


def _distinguishing_suffixes(group: Sequence[Score]) -> list[str]:
    """For cards whose label is identical: a field only counts when it
    differs within the group, and fields are added until every card is
    unique. The entry date is the last resort, and only when it differs;
    cards that nothing can tell apart keep the plain label."""
    chosen: list[Callable[[Score], str]] = []

    def _values(score: Score) -> tuple[str, ...]:
        return tuple(field(score) for field in chosen)

    def _unique() -> bool:
        return len({_values(score) for score in group}) == len(group)

    for field in _DISAMBIGUATION_FIELDS:
        if len({field(score) for score in group}) < 2:
            continue
        chosen.append(field)
        if _unique():
            break
    if not _unique() and len({_entered_on(score) for score in group}) > 1:
        chosen.append(_entered_on)
    return [", ".join(part for part in _values(score) if part) for score in group]


def _disambiguated_labels(scores: Sequence[Score]) -> list[str]:
    """The search labels, with a suffix only for hits that would otherwise
    read exactly like another hit of the same result list."""
    labels = [_label_for_score(score) for score in scores]
    positions_by_label: dict[str, list[int]] = {}
    for position, label in enumerate(labels):
        positions_by_label.setdefault(label, []).append(position)
    for label, positions in positions_by_label.items():
        if len(positions) < 2:
            continue
        suffixes = _distinguishing_suffixes(
            [scores[position] for position in positions]
        )
        for position, suffix in zip(positions, suffixes, strict=True):
            if suffix:
                labels[position] = f"{label} - {suffix}"
    return labels


def get_score(db: Session, score_id: uuid.UUID) -> ScoreResponse:
    return _to_response(_get_or_404(db, score_id))


def create_score(db: Session, data: ScoreRequest) -> ScoreResponse:
    """No uniqueness rule on work, composer and part: the archive holds
    several versions of one work (each its own card, identified by its id),
    mirroring the historically grown paper archive."""
    score = Score()
    _apply_fields(score, data)
    db.add(score)
    db.commit()
    return _to_response(score)


def update_score(db: Session, score_id: uuid.UUID, data: ScoreRequest) -> ScoreResponse:
    score = _get_or_404(db, score_id)
    _apply_fields(score, data)
    db.commit()
    return _to_response(score)
