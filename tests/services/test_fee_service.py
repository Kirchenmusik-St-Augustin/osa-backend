import uuid

import pytest
from sqlalchemy.orm import Session

from app.schemas.fee import FeeRequest
from app.services import fee_service


def _unique(base: str = "Fee") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _request(name: str | None = None, *, amount: int = 80) -> FeeRequest:
    return FeeRequest(name=name or _unique(), amount=amount)


class TestListFees:
    def test_returns_alphabetically_ordered(self, db_session: Session):
        marker_a, marker_z = _unique("AAA"), _unique("ZZZ")
        fee_service.create_fee(db_session, _request(marker_z))
        fee_service.create_fee(db_session, _request(marker_a))
        names = [fee.name for fee in fee_service.list_fees(db_session)]
        assert names.index(marker_a) < names.index(marker_z)


class TestCreateFee:
    def test_creates_with_given_name_and_amount(self, db_session: Session):
        name = _unique()
        fee = fee_service.create_fee(db_session, _request(name, amount=130))
        assert fee.name == name
        assert fee.amount == 130

    def test_name_too_short_is_rejected(self, db_session: Session):
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(min_length=3)
            FeeRequest(name="ab", amount=10)

    def test_duplicate_name_is_rejected(self, db_session: Session):
        name = _unique()
        fee_service.create_fee(db_session, _request(name))
        with pytest.raises(fee_service.FeeValidationError) as exc_info:
            fee_service.create_fee(db_session, _request(name))
        assert exc_info.value.errors == [("name", "Der Name ist bereits vergeben.")]

    def test_amount_out_of_range_is_rejected(self, db_session: Session):
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(le=999)
            FeeRequest(name=_unique(), amount=1000)


class TestUpdateFee:
    def test_updates_name_and_amount(self, db_session: Session):
        fee = fee_service.create_fee(db_session, _request(amount=50))
        new_name = _unique("Renamed")
        updated = fee_service.update_fee(
            db_session, fee.id, _request(new_name, amount=99)
        )
        assert updated.name == new_name
        assert updated.amount == 99

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(fee_service.FeeNotFoundError):
            fee_service.update_fee(db_session, -1, _request())

    def test_keeping_own_name_does_not_trigger_uniqueness_error(
        self, db_session: Session
    ):
        fee = fee_service.create_fee(db_session, _request())
        updated = fee_service.update_fee(
            db_session, fee.id, _request(fee.name, amount=fee.amount + 1)
        )
        assert updated.amount == fee.amount + 1

    def test_duplicate_name_against_another_fee_is_rejected(self, db_session: Session):
        other = fee_service.create_fee(db_session, _request())
        fee = fee_service.create_fee(db_session, _request())
        with pytest.raises(fee_service.FeeValidationError) as exc_info:
            fee_service.update_fee(db_session, fee.id, _request(other.name))
        assert exc_info.value.errors == [("name", "Der Name ist bereits vergeben.")]


class TestDeleteFee:
    def test_deletes_without_dependency_check(self, db_session: Session):
        fee = fee_service.create_fee(db_session, _request())
        fee_service.delete_fee(db_session, fee.id)
        assert fee.name not in [f.name for f in fee_service.list_fees(db_session)]

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(fee_service.FeeNotFoundError):
            fee_service.delete_fee(db_session, -1)
