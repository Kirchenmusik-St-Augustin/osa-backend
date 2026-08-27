from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.fee import Fee
from app.schemas.fee import FeeRequest, FeeResponse


class FeeNotFoundError(Exception):
    """Raised when `fee_id` doesn't exist."""


class FeeValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's SaveRequest
    error bags -- 1:1 coreelement_service.CoreelementValidationError
    pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Fee validation failed")


def _name_taken(db: Session, name: str, exclude_id: int | None) -> bool:
    stmt = select(Fee.id).where(Fee.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Fee.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def _validate(
    db: Session, data: FeeRequest, exclude_id: int | None
) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    if _name_taken(db, data.name.strip(), exclude_id):
        errors.append(("name", "Der Name ist bereits vergeben."))
    return errors


def _get_or_404(db: Session, fee_id: int) -> Fee:
    result = db.execute(select(Fee).where(Fee.id == fee_id))
    fee = result.scalar_one_or_none()
    if fee is None:
        raise FeeNotFoundError
    return fee


def _to_response(fee: Fee) -> FeeResponse:
    return FeeResponse(id=fee.id, name=fee.name, amount=fee.amount)


def list_fees(db: Session) -> list[FeeResponse]:
    # Legacy's `Fee::OrderByName` global scope -- alphabetical, since `fees`
    # has no `order` column (see app.db.models.fee.Fee docstring).
    fees = db.execute(select(Fee).order_by(Fee.name)).scalars().all()
    return [_to_response(fee) for fee in fees]


def create_fee(db: Session, data: FeeRequest) -> FeeResponse:
    errors = _validate(db, data, exclude_id=None)
    if errors:
        raise FeeValidationError(errors)

    now = datetime.now(UTC)
    fee = Fee(
        name=data.name.strip(), amount=data.amount, created_at=now, updated_at=now
    )
    db.add(fee)
    db.commit()
    return _to_response(fee)


def update_fee(db: Session, fee_id: int, data: FeeRequest) -> FeeResponse:
    fee = _get_or_404(db, fee_id)
    errors = _validate(db, data, exclude_id=fee_id)
    if errors:
        raise FeeValidationError(errors)

    fee.name = data.name.strip()
    fee.amount = data.amount
    fee.updated_at = datetime.now(UTC)
    db.commit()
    return _to_response(fee)


def delete_fee(db: Session, fee_id: int) -> None:
    # No has_dependencies check -- Legacy's own DestroyRequest has an empty
    # rules() too, since bookings.fee/booking_logs.fee are plain integer
    # copies of a Fee's amount, never an FK to fees.id.
    fee = _get_or_404(db, fee_id)
    db.delete(fee)
    db.commit()
