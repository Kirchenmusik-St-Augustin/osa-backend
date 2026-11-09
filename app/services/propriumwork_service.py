from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.db.models.performance_proprium import PerformanceProprium
from app.db.models.propriumwork import Propriumwork
from app.schemas.propriumwork import PropriumworkRequest, PropriumworkResponse
from app.services.errors import (
    DomainValidationError,
    FieldError,
    GeneralValidationError,
    NotFoundError,
)
from app.services.work_common import (
    WorkKind,
    search_works,
    validate_work_fields,
    work_response,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from app.schemas.base import IdLabelOutput

_WORK_KIND = WorkKind(model=Propriumwork, response_type=PropriumworkResponse)

_IN_USE_DETAIL = "Das Element kann nicht gelöscht werden, da es noch in Verwendung ist."


class PropriumworkNotFoundError(NotFoundError):
    """Raised when `propriumwork_id` doesn't exist."""


class PropriumworkValidationError(DomainValidationError):
    """Field-level validation failures, one (field, message) pair per
    failing field."""


class PropriumworkInUseError(GeneralValidationError):
    """Raised when delete is blocked by a Performance referencing this
    Propriumwork. Unlike Ordinariumwork
    (a direct `ordinariumwork_id` column on `performances`), a Propriumwork
    is only referenced through the `performance_proprium` pivot table."""

    def __init__(self) -> None:
        super().__init__(_IN_USE_DETAIL)


def _get_or_404(db: Session, propriumwork_id: uuid.UUID) -> Propriumwork:
    result = db.execute(select(Propriumwork).where(Propriumwork.id == propriumwork_id))
    propriumwork = result.scalar_one_or_none()
    if propriumwork is None:
        raise PropriumworkNotFoundError
    return propriumwork


def _validate(
    db: Session, data: PropriumworkRequest, exclude_id: uuid.UUID | None
) -> list[FieldError]:
    return validate_work_fields(
        db,
        _WORK_KIND,
        name=data.name,
        artist_id=data.artist_id,
        duration=data.duration,
        exclude_id=exclude_id,
    )


def _to_response(db: Session, propriumwork: Propriumwork) -> PropriumworkResponse:
    return work_response(db, _WORK_KIND, propriumwork)


def search_propriumworks(db: Session, query: str) -> Sequence[IdLabelOutput]:
    return search_works(db, _WORK_KIND, query)


def create_propriumwork(db: Session, data: PropriumworkRequest) -> PropriumworkResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise PropriumworkValidationError(errors)

    propriumwork = Propriumwork(
        name=data.name,
        description=data.description,
        artist_id=data.artist_id,
        duration=data.duration,
        demanding=data.demanding,
    )
    db.add(propriumwork)
    db.commit()
    return _to_response(db, propriumwork)


def update_propriumwork(
    db: Session, propriumwork_id: uuid.UUID, data: PropriumworkRequest
) -> PropriumworkResponse:
    propriumwork = _get_or_404(db, propriumwork_id)
    errors = _validate(db, data, exclude_id=propriumwork_id)
    if errors:
        raise PropriumworkValidationError(errors)

    propriumwork.name = data.name
    propriumwork.description = data.description
    propriumwork.artist_id = data.artist_id
    propriumwork.duration = data.duration
    propriumwork.demanding = data.demanding
    db.commit()
    return _to_response(db, propriumwork)


def get_propriumwork(db: Session, propriumwork_id: uuid.UUID) -> PropriumworkResponse:
    propriumwork = _get_or_404(db, propriumwork_id)
    return _to_response(db, propriumwork)


def _propriumwork_has_dependencies(db: Session, propriumwork_id: uuid.UUID) -> bool:
    count = db.execute(
        select(func.count())
        .select_from(PerformanceProprium)
        .where(PerformanceProprium.propriumwork_id == propriumwork_id)
    ).scalar_one()
    return count > 0


def delete_propriumwork(db: Session, propriumwork_id: uuid.UUID) -> None:
    propriumwork = _get_or_404(db, propriumwork_id)
    if _propriumwork_has_dependencies(db, propriumwork_id):
        raise PropriumworkInUseError
    db.delete(propriumwork)
    db.commit()
