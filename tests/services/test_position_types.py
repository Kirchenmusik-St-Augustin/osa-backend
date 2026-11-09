import pytest

from app.db.models.booking import Booking
from app.db.models.ordinariumwork_position import OrdinariumworkPosition
from app.db.models.performance_position import PerformancePosition
from app.db.models.user_position import UserPosition
from app.services.position_types import POSITION_TYPES, PositionType, position_column

_EXPECTED_COLUMN_NAMES: dict[PositionType, str] = {
    "instruments": "instrument_id",
    "voices": "voice_id",
    "choirjobs": "choirjob_id",
}


@pytest.mark.parametrize("model", [Booking, PerformancePosition, UserPosition])
@pytest.mark.parametrize("position_type", POSITION_TYPES)
def test_position_column_is_the_foreign_key_column_of_the_type(
    model: type, position_type: PositionType
):
    column = position_column(model, position_type)

    assert column is getattr(model, _EXPECTED_COLUMN_NAMES[position_type])


@pytest.mark.parametrize("position_type", ["instruments", "voices"])
def test_position_column_serves_the_ordinarium_positions(position_type: PositionType):
    column = position_column(OrdinariumworkPosition, position_type)

    assert column is getattr(
        OrdinariumworkPosition, _EXPECTED_COLUMN_NAMES[position_type]
    )


def test_position_column_has_no_choirjob_column_on_ordinarium_positions():
    with pytest.raises(AttributeError):
        position_column(OrdinariumworkPosition, "choirjobs")
