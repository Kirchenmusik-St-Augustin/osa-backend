from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.human_names import label_for_name, normalize_givenname, normalize_surname
from app.db.models.score import Score
from app.schemas.score import (
    ScoreFieldConfig,
    ScoreRequest,
    ScoreResponse,
    ScoreSearchResult,
)
from app.services.errors import DomainValidationError, FieldError, NotFoundError
from app.services.score_fields import SCORE_FIELDS

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from sqlalchemy.orm import Session

    from app.services.score_fields import ScoreFieldSpec

_SEARCH_RESULT_LIMIT = 50


class ScoreNotFoundError(NotFoundError):
    """Raised when `score_id` doesn't exist."""


class ScoreValidationError(DomainValidationError):
    """Field-level validation failures, one (field, message) pair per
    failing field -- same pattern as fee_service.FeeValidationError."""


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


def _werk_taken(
    db: Session,
    *,
    werk: str,
    surname: str | None,
    givenname: str | None,
    teil: str | None,
    exclude_id: uuid.UUID | None,
) -> bool:
    """Compound-unique rule: `werk` must be unique WITHIN the (surname,
    givenname, teil) scope, not globally. SQLAlchemy's `== None` below
    compiles to `IS NULL`, so a duplicate `werk` is also detected when
    surname/givenname/teil are all blank (a rare blank-composer case that a
    literal `= NULL` comparison would never match)."""
    stmt = select(Score.id).where(
        Score.werk == werk,
        Score.surname == surname,
        Score.givenname == givenname,
        Score.teil == teil,
    )
    if exclude_id is not None:
        stmt = stmt.where(Score.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _validate(
    db: Session, data: ScoreRequest, exclude_id: uuid.UUID | None
) -> list[FieldError]:
    errors: list[FieldError] = []
    if _werk_taken(
        db,
        werk=data.werk,
        surname=_normalized_name(data.surname, normalize_surname),
        givenname=_normalized_name(data.givenname, normalize_givenname),
        teil=data.teil,
        exclude_id=exclude_id,
    ):
        errors.append(
            FieldError(
                "werk", "Name, Komponist und Werkteil müssen zusammen eindeutig sein"
            )
        )
    return errors


def search_scores(db: Session, query: str) -> list[ScoreSearchResult]:
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
        .where(*[combined.like(f"%{word}%") for word in words])
        .order_by(Score.surname)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    scores = db.execute(stmt).scalars().all()
    return [
        ScoreSearchResult(id=score.id, label=_label_for_score(score))
        for score in scores
    ]


def _label_for_score(score: Score) -> str:
    name = label_for_name(score.surname or "", score.givenname)
    label = f"{name}: {score.werk or ''}"
    if score.teil:
        label += f" / {score.teil}"
    return label


def get_score(db: Session, score_id: uuid.UUID) -> ScoreResponse:
    return _to_response(_get_or_404(db, score_id))


def create_score(db: Session, data: ScoreRequest) -> ScoreResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise ScoreValidationError(errors)

    score = Score()
    _apply_fields(score, data)
    db.add(score)
    db.commit()
    return _to_response(score)


def update_score(db: Session, score_id: uuid.UUID, data: ScoreRequest) -> ScoreResponse:
    score = _get_or_404(db, score_id)
    errors = _validate(db, data, exclude_id=score_id)
    if errors:
        raise ScoreValidationError(errors)

    _apply_fields(score, data)
    db.commit()
    return _to_response(score)
