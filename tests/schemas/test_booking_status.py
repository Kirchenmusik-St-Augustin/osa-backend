import pytest
from pydantic import ValidationError

from app.schemas.performance import BookingStatus, BookingStatusOutput


class TestBookingStatusWireFormat:
    def test_values_are_the_integers_the_frontend_consumes(self):
        assert [status.value for status in BookingStatus] == [0, 1, 2, 3, 4, 5]

    @pytest.mark.parametrize("status", list(BookingStatus))
    def test_serializes_as_a_plain_integer(self, status: BookingStatus):
        dumped = BookingStatusOutput(status=status).model_dump(mode="json")

        assert dumped["status"] == status.value
        assert type(dumped["status"]) is int

    def test_parses_a_plain_integer_back_into_the_enum(self):
        assert BookingStatusOutput.model_validate({"status": 4}).status is (
            BookingStatus.BOOKED
        )

    def test_rejects_an_unknown_status_code(self):
        with pytest.raises(ValidationError):
            BookingStatusOutput.model_validate({"status": 6})
