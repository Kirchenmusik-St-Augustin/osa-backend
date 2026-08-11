from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.human_names import label_for_name, normalize_givenname, normalize_surname
from app.db.models.score import Score
from app.schemas.score import (
    ScoreFieldConfig,
    ScoreRequest,
    ScoreResponse,
    ScoreSearchResult,
)
from app.services.score_fields import SCORE_FIELDS

_SEARCH_RESULT_LIMIT = 50


class ScoreNotFoundError(Exception):
    """Raised when `score_id` doesn't exist."""


class ScoreValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 fee_service.FeeValidationError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Score validation failed")


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


def get_defaults() -> dict[str, str | int]:
    """1:1 Legacy's `Score::setDefaults()`: "" for text/textarea, the
    first `values` entry for select, 0 for every number field."""
    defaults: dict[str, str | int] = {}
    for name, spec in SCORE_FIELDS.items():
        if spec.kind == "number":
            defaults[name] = 0
        elif spec.kind == "select":
            defaults[name] = spec.values[0] if spec.values else ""
        else:
            defaults[name] = ""
    return defaults


def _fields_dict(score: Score) -> dict[str, str | int]:
    """Reads all 94 field values off `score`, coalescing NULL (possible
    for pre-existing/imported rows) to the same "empty" value Legacy's own
    setDefaults() would produce -- Optional never needs to cross the API
    boundary (see ScoreRequest's docstring)."""
    result: dict[str, str | int] = {}
    for name, spec in SCORE_FIELDS.items():
        value = getattr(score, name)
        if spec.kind == "number":
            result[name] = value if value is not None else 0
        else:
            result[name] = value if value is not None else ""
    return result


def _storage_value(value: str | int, kind: str) -> str | int | None:
    """1:1 Legacy's `ConvertEmptyStringsToNull` middleware (a default
    Laravel `web`-group middleware): an empty optional text/textarea/
    select submission is stored as NULL, never "". Required for the
    "select" columns specifically -- their CHECK constraints (see
    app.db.models.score) do not list "" as an allowed value, so storing a
    literal "" there would violate the constraint outright, not just
    diverge from Legacy's real data shape."""
    if kind == "number" or value != "":
        return value
    return None


def _apply_fields(score: Score, data: ScoreRequest) -> None:
    payload = data.model_dump()
    for name, spec in SCORE_FIELDS.items():
        if name in ("surname", "givenname"):
            continue  # set via the HasHumanNames mutators below instead
        setattr(score, name, _storage_value(payload[name], spec.kind))
    # HasHumanNames mutators -- 1:1 the same normalization User/Artist
    # already apply (app.core.human_names), then the same empty->NULL
    # normalization as every other optional text field above.
    score.surname = normalize_surname(data.surname) or None
    score.givenname = normalize_givenname(data.givenname) or None


def _to_response(score: Score) -> ScoreResponse:
    return ScoreResponse(
        id=score.id,
        created_at=score.created_at,
        updated_at=score.updated_at,
        fields=_fields_dict(score),
    )


def _get_or_404(db: Session, score_id: int) -> Score:
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
    exclude_id: int | None,
) -> bool:
    """1:1 Legacy's SaveRequest compound-unique rule: `werk` must be
    unique WITHIN the (surname, givenname, teil) scope, not globally.
    Deliberate, documented divergence: Legacy's own Eloquent `where(['col'
    => null])` binds a literal `= NULL` comparison, which SQL never
    matches -- meaning Legacy itself can never detect a duplicate `werk`
    when surname/givenname/teil are all blank. SQLAlchemy's `== None`
    below correctly compiles to `IS NULL` instead, so this port does
    catch that (rare, blank-composer) case Legacy would silently miss.
    Treated as a correctness improvement, not a business-result change
    worth replicating the bug for."""
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
    db: Session, data: ScoreRequest, exclude_id: int | None
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    if _werk_taken(
        db,
        werk=data.werk,
        surname=normalize_surname(data.surname) or None,
        givenname=normalize_givenname(data.givenname) or None,
        teil=data.teil or None,
        exclude_id=exclude_id,
    ):
        errors.append(
            ("werk", "Name, Komponist und Werkteil müssen zusammen eindeutig sein")
        )
    return errors


def search_scores(db: Session, query: str) -> list[ScoreSearchResult]:
    """Real indexed-ish DB query, replacing Legacy's `Score::search()`
    anti-pattern (loads the entire table into PHP, filters in memory).
    Every whitespace-separated word in `query` must appear somewhere in
    "surname givenname werk teil" (mirrors Legacy's `Str::containsAll`
    semantics). `coalesce()` on every nullable column -- PHP string
    concatenation silently treats NULL as "", SQL `||` does not."""
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


def get_score(db: Session, score_id: int) -> ScoreResponse:
    return _to_response(_get_or_404(db, score_id))


def create_score(db: Session, data: ScoreRequest) -> ScoreResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise ScoreValidationError(errors)

    now = datetime.now(UTC)
    score = Score(created_at=now, updated_at=now)
    _apply_fields(score, data)
    db.add(score)
    db.commit()
    return _to_response(score)


def update_score(db: Session, score_id: int, data: ScoreRequest) -> ScoreResponse:
    score = _get_or_404(db, score_id)
    errors = _validate(db, data, exclude_id=score_id)
    if errors:
        raise ScoreValidationError(errors)

    _apply_fields(score, data)
    score.updated_at = datetime.now(UTC)
    db.commit()
    return _to_response(score)
