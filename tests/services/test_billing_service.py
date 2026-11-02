from typing import TYPE_CHECKING

import pytest

from app.services import billing_service, cast_service
from tests.booking_helpers import create_instrument, create_performance, move_to_past

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TestGetBilling:
    def test_billing_sums_booked_and_unfilled_slots(
        self, db_session: Session, make_user
    ):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 2})
        user = make_user()
        cast_service.save_cast_item(
            db_session,
            performance_id,
            "instruments",
            instrument.id,
            new_cast=[(user.id, 80)],
            old_quantity=None,
        )
        current_user = make_user()

        billing = billing_service.get_billing(db_session, performance_id, current_user)

        assert (
            billing.billing.instruments.items[0].sum == 80 + 60
        )  # booked + default fee slot
        assert billing.billing.instruments.count == 2

    @pytest.mark.parametrize(
        ("instrument_count", "expected_fee"),
        [(0, 0), (1, 30), (12, 30), (13, 55)],
    )
    def test_instruments_orgfee_thresholds(self, instrument_count, expected_fee):
        orgfee = billing_service._org_fee(instrument_count, 0)
        assert orgfee.instruments == expected_fee

    @pytest.mark.parametrize(("choirjob_count", "expected_fee"), [(0, 0), (1, 15)])
    def test_choirjobs_orgfee_thresholds(self, choirjob_count, expected_fee):
        orgfee = billing_service._org_fee(0, choirjob_count)
        assert orgfee.choirjobs == expected_fee

    def test_billing_has_no_past_lock(self, db_session: Session, make_user):
        instrument = create_instrument(db_session)
        performance_id = create_performance(db_session, instruments={instrument.id: 1})
        move_to_past(db_session, performance_id)
        current_user = make_user()

        billing = billing_service.get_billing(
            db_session, performance_id, current_user
        )  # no raise

        assert billing.billing.sum >= 0
